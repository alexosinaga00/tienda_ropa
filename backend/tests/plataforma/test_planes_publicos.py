"""CU-04: GET /api/v1/public/planes (sin sesión). Lista los planes activos para la
portada pública, ordenados por `max_sucursales` y luego por `id`, con solo los campos
del contrato (sin `id` ni `activo`). `plan` es una tabla global: no se filtra por empresa
y la ruta está exenta de la suscripción activa."""

from sqlalchemy import select, update

from app.core.tenant import sin_filtro
from app.plataforma.models import Plan, Suscripcion

PLANES = "/api/v1/public/planes"
PLATAFORMA = "/api/v1/plataforma"
CAMPOS = {
    "codigo",
    "nombre",
    "max_sucursales",
    "max_copias_historial",
    "plazo_cambio_horas_defecto",
    "precio_mensual_bs",
    "gestion_productos",
    "gestion_ventas",
    "reservas",
    "reportes_convencionales",
    "reportes_ia",
    "operacion_offline",
    "analitica_ml",
    "copias_seguridad",
}


def _codigos(respuesta) -> list[str]:
    assert respuesta.status_code == 200, respuesta.text
    return [p["codigo"] for p in respuesta.json()]


def _crear_plan(client, headers, codigo: str, max_sucursales: int, **extra):
    respuesta = client.post(
        f"{PLATAFORMA}/planes",
        json={"codigo": codigo, "nombre": f"Plan {codigo}", "max_sucursales": max_sucursales, **extra},
        headers=headers,
    )
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()


def test_responde_200_sin_token_y_trae_los_planes_sembrados(client_por_peticion):
    respuesta = client_por_peticion.get(PLANES)

    assert respuesta.status_code == 200, respuesta.text
    assert {"basico", "profesional"} <= set(_codigos(respuesta))


def test_trae_solo_los_campos_del_contrato_sin_id_ni_activo(client_por_peticion):
    planes = client_por_peticion.get(PLANES).json()

    assert planes
    for plan in planes:
        assert set(plan) == CAMPOS
        assert "id" not in plan and "activo" not in plan
        assert isinstance(plan["max_sucursales"], int) and isinstance(plan["analitica_ml"], bool)


def test_solo_aparecen_los_planes_activos(client_por_peticion, superadmin_headers):
    plan = _crear_plan(client_por_peticion, superadmin_headers, "temporal", 3)
    assert "temporal" in _codigos(client_por_peticion.get(PLANES))

    # Sin suscripciones, se puede dar de baja: deja de salir en la portada.
    baja = client_por_peticion.put(f"{PLATAFORMA}/planes/{plan['id']}", json={"activo": False}, headers=superadmin_headers)
    assert baja.status_code == 200, baja.text

    codigos = _codigos(client_por_peticion.get(PLANES))
    assert "temporal" not in codigos
    assert {"basico", "profesional"} <= set(codigos)


def test_se_ordenan_por_max_sucursales_y_luego_por_id(client_por_peticion, superadmin_headers):
    # Se crean fuera de orden: el de 7 sucursales primero, luego dos con 1 y 99.
    _crear_plan(client_por_peticion, superadmin_headers, "plan-siete", 7)
    _crear_plan(client_por_peticion, superadmin_headers, "plan-noventa", 99)
    _crear_plan(client_por_peticion, superadmin_headers, "plan-uno-b", 1)
    _crear_plan(client_por_peticion, superadmin_headers, "plan-uno-c", 1)

    planes = client_por_peticion.get(PLANES).json()

    claves = [(p["max_sucursales"], p["codigo"]) for p in planes]
    assert [c[0] for c in claves] == sorted(c[0] for c in claves)
    codigos = [p["codigo"] for p in planes]
    # Mismo máximo: manda el id, o sea el orden de alta.
    assert codigos.index("plan-uno-b") < codigos.index("plan-uno-c")
    assert codigos.index("plan-siete") < codigos.index("plan-noventa")
    assert codigos[-1] == "plan-noventa"


def test_refleja_la_edicion_de_un_plan(client_por_peticion, db_session, superadmin_headers):
    antes = {p["codigo"]: p for p in client_por_peticion.get(PLANES).json()}["basico"]
    assert antes["analitica_ml"] is False

    plan_id = db_session.scalar(select(Plan.id).where(Plan.codigo == "basico"))
    editado = client_por_peticion.put(
        f"{PLATAFORMA}/planes/{plan_id}",
        json={"max_sucursales": 4, "analitica_ml": True, "plazo_cambio_horas_defecto": 36, "nombre": "Básico plus"},
        headers=superadmin_headers,
    )
    assert editado.status_code == 200, editado.text

    despues = {p["codigo"]: p for p in client_por_peticion.get(PLANES).json()}["basico"]
    assert despues["max_sucursales"] == 4
    assert despues["analitica_ml"] is True
    assert despues["plazo_cambio_horas_defecto"] == 36
    assert despues["nombre"] == "Básico plus"


def test_funciona_aunque_ninguna_empresa_tenga_suscripcion_activa(client_por_peticion, db_session, dos_empresas):
    db_session.execute(
        sin_filtro(update(Suscripcion).values(estado="suspendida")),
        execution_options={"synchronize_session": False},
    )
    db_session.commit()

    respuesta = client_por_peticion.get(PLANES)

    assert respuesta.status_code == 200, respuesta.text
    assert {"basico", "profesional"} <= set(_codigos(respuesta))


def test_no_filtra_datos_de_empresas(client_por_peticion, dos_empresas):
    respuesta = client_por_peticion.get(PLANES)

    texto = respuesta.text.lower()
    assert respuesta.status_code == 200
    for ajeno in ("tienda-a", "tienda-b", "fashionstore", "admin@", "empresa", "suscripcion"):
        assert ajeno not in texto
    for plan in respuesta.json():
        assert set(plan) == CAMPOS
