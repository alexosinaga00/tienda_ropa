"""E05, 4.7: planes y suscripción como parte del aislamiento (RNF01/RNF02).

Comprueba que las restricciones por plan y por suscripción las aplica el backend y que no
dependen de una empresa vecina:

  a) tabla de verdad funcionalidad x plan, leída de la tabla `plan` (no supuesta);
  b) estados de la suscripción x clase de ruta (y qué rutas siguen funcionando);
  c) independencia: lo que le pasa a una empresa no le pasa a otra;
  d) límite de sucursales por plan;
  e) formato de los tres errores funcionales;
  f) toda ruta de negocio declara su compuerta de plan o está exenta con razón escrita.

A (Profesional) y B (Básico) del universo compartido solo se usan para LEER o para pruebas que
no los alteran. Todo lo que cambia un estado global (suspender, vencer, cancelar, desactivar,
cambiar de plan, llenar el cupo de sucursales) se hace con EMPRESAS DESCARTABLES, creadas por la
`fabrica` de este archivo y borradas del todo al terminar el módulo (el universo queda igual).
"""

import datetime as dt
import hashlib
import hmac
import itertools
import json
import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, text

from app.comercial.repository import VW_VENTAS_DETALLE_V2_SQL
from app.core.config import get_settings
from app.core.database import Base, get_db
from app.core.planes import FUNCIONALIDADES, RUTAS_SIN_SUSCRIPCION
from app.core.security import crear_access_token
from app.core.tenant import en_empresa, fijar_empresa, sin_filtro
from app.main import app
from app.plataforma.models import Empresa, Plan, Suscripcion, Usuario
from app.plataforma.repository import UsuarioRepository
from app.plataforma.schemas import UsuarioCrear
from tests.conftest import EmpresaDePrueba, crear_empresa, crear_superadmin_de_prueba, token_de

from .oraculo import ID_INEXISTENTE, armar, inexistente_para, parametros_de
from .plantillas import ARCHIVOS
from .rutas_esperadas import (
    CREA_O_ACCION,
    LISTADO,
    MATRIZ,
    POR_ID,
    PROPIA,
    PUBLICA,
    RUTAS,
)
from .universo import CLAVE

API = "/api/v1"
CLASES_DE_NEGOCIO = (POR_ID, LISTADO, CREA_O_ACCION, PROPIA)
HOY = dt.date.today()
AYER = HOY - dt.timedelta(days=1)

# Rutas que NO exigen suscripción activa (copia literal de la regla del contrato: si
# `core.planes.RUTAS_SIN_SUSCRIPCION` cambia, la prueba de más abajo obliga a revisar este archivo).
PREFIJOS_EXENTOS_DE_SUSCRIPCION = (
    "/health",
    "/api/v1/auth/",
    "/api/v1/mi-empresa",
    "/api/v1/plataforma/",
    "/api/v1/public/tiendas",
    "/api/v1/public/planes",
    "/api/v1/public/contratacion/",  # contratación pública (prueba gratuita): no es una tienda
    "/api/v1/pagos/webhook/",
    "/api/v1/pagos/qr/",
    "/api/v1/tareas/",
    "/api/v1/sincronizacion/lote",  # E07: guarda el rechazo de cada operación con su motivo (D16)
)
RUTA_TIENDA = re.compile(r"^/api/v1/public/[^/]+/tienda$")
TOKEN_SERVICIO = {"X-Service-Token": "token-de-pruebas"}
SECRETO_LIBELULA = get_settings().libelula_webhook_secret


def _es_exenta_de_suscripcion(ruta: str) -> bool:
    return ruta.startswith(PREFIJOS_EXENTOS_DE_SUSCRIPCION) or bool(RUTA_TIENDA.match(ruta))


# =================================================================================================
# Fábrica de empresas descartables y fixtures del módulo
# =================================================================================================


class Fabrica:
    """Crea empresas descartables sobre el motor del universo y las borra al terminar."""

    def __init__(self, mundo):
        self.mundo = mundo
        self.empresas: list[int] = []
        self.superadmins: list[int] = []
        self._contador = itertools.count(1)
        self._prefijo = f"pl{id(self) % 10_000:04d}"

    # -- altas -------------------------------------------------------------------------------

    def crear(self, plan: str = "profesional", nombre: str | None = None) -> EmpresaDePrueba:
        """Empresa con su suscripción activa del `plan` y su administrador (rol administrador)."""
        n = next(self._contador)
        codigo = f"{self._prefijo}-{n}"
        repo = UsuarioRepository()
        with self.mundo.sesiones() as db:
            empresa = crear_empresa(db, codigo, plan=plan, nombre=nombre or f"Descartable {self._prefijo} {n}")
            self.empresas.append(empresa.id)
            fijar_empresa(db, empresa.id)
            admin = repo.crear(
                db, UsuarioCrear(nombre="Admin", apellido=codigo, email="admin@tienda.bo", password=CLAVE)
            )
            repo.asignar_roles(db, admin, ["administrador"])
            return EmpresaDePrueba(id=empresa.id, codigo=codigo, admin_id=admin.id, headers=token_de(db, admin))

    def superadmin(self) -> dict:
        """Cabeceras de un superadministrador propio (correo distinto al de otros archivos)."""
        correo = f"super-{self._prefijo}@plataforma.example.com"
        with self.mundo.sesiones() as db:
            usuario_id = crear_superadmin_de_prueba(db, correo, CLAVE)
        self.superadmins.append(usuario_id)
        token = crear_access_token(usuario_id, ["superadministrador"], [], empresa_id=None)
        return {"Authorization": f"Bearer {token}"}

    # -- cambios de estado directos en la base (como los dejaría el tiempo o una tarea) ---------

    def cambiar_suscripcion(self, empresa_id: int, **campos) -> None:
        with self.mundo.sesiones() as db:
            with en_empresa(db, empresa_id):
                suscripcion = db.scalar(select(Suscripcion).where(Suscripcion.estado != "cancelada"))
                for campo, valor in campos.items():
                    setattr(suscripcion, campo, valor)
            db.commit()

    def quitar_suscripciones(self, empresa_id: int) -> None:
        with self.mundo.sesiones() as db:
            with en_empresa(db, empresa_id):
                for suscripcion in db.scalars(select(Suscripcion)).all():
                    db.delete(suscripcion)
            db.commit()

    def desactivar(self, empresa_id: int) -> None:
        with self.mundo.sesiones() as db:
            db.get(Empresa, empresa_id).activo = False
            db.commit()

    def plan_de(self, codigo_plan: str) -> Plan:
        with self.mundo.sesiones() as db:
            plan = db.scalar(select(Plan).where(Plan.codigo == codigo_plan))
            db.expunge(plan)
            return plan

    # -- limpieza --------------------------------------------------------------------------------

    def limpiar(self) -> None:
        """Borra TODO rastro de las empresas descartables y de los superadministradores propios:
        el universo y las demás pruebas del paquete quedan como estaban."""
        if not self.empresas and not self.superadmins:
            return
        with self.mundo.engine.begin() as conexion:
            usuarios = select(Usuario.id).where(Usuario.empresa_id.in_(self.empresas)) if self.empresas else None
            tabla_usuario_rol = Base.metadata.tables["usuario_rol"]
            if usuarios is not None:
                conexion.execute(delete(tabla_usuario_rol).where(tabla_usuario_rol.c.usuario_id.in_(usuarios)))
            if self.superadmins:
                conexion.execute(delete(tabla_usuario_rol).where(tabla_usuario_rol.c.usuario_id.in_(self.superadmins)))
            for tabla in reversed(Base.metadata.sorted_tables):
                if "empresa_id" in tabla.c and self.empresas:
                    conexion.execute(delete(tabla).where(tabla.c.empresa_id.in_(self.empresas)))
            if self.superadmins:
                conexion.execute(delete(Usuario.__table__).where(Usuario.__table__.c.id.in_(self.superadmins)))
            if self.empresas:
                conexion.execute(delete(Empresa.__table__).where(Empresa.__table__.c.id.in_(self.empresas)))


@pytest.fixture(scope="module")
def fabrica(_mundo):
    f = Fabrica(_mundo)
    # La vista de ventas solo existe en PostgreSQL de forma permanente; para que los reportes
    # respondan 200 en SQLite (y no un 500 por vista inexistente) se crea durante este módulo.
    with _mundo.engine.begin() as conexion:
        conexion.execute(text("DROP VIEW IF EXISTS vw_ventas_detalle"))
        conexion.execute(text(VW_VENTAS_DETALLE_V2_SQL))
    try:
        yield f
    finally:
        f.limpiar()
        with _mundo.engine.begin() as conexion:
            conexion.execute(text("DROP VIEW IF EXISTS vw_ventas_detalle"))


@pytest.fixture(scope="module")
def superadmin(fabrica) -> dict:
    return fabrica.superadmin()


@pytest.fixture()
def http(mundo, monkeypatch) -> TestClient:
    """Cliente que devuelve el 5xx en vez de relanzar la excepción: un 5xx es un hallazgo que la
    prueba muestra, no una interrupción. Sin clave de Groq: ninguna petición sale a la red."""
    monkeypatch.setattr(get_settings(), "groq_api_key", "")
    return TestClient(app, raise_server_exceptions=False)


def _json(respuesta) -> dict:
    try:
        cuerpo = respuesta.json()
    except ValueError:
        return {}
    return cuerpo if isinstance(cuerpo, dict) else {}


# Rutas con usuario OPCIONAL (get_current_user_opcional) o sin dependencia que corte antes: validan el
# cuerpo o la query ANTES de mirar quién llama, así que necesitan una petición bien formada para que
# la prueba vea la respuesta que importa. (todas inofensivas: ids inexistentes y textos sueltos)
PETICIONES_VALIDAS = {
    ("GET", f"{API}/inventario/disponibilidad"): {"params": {"variante_id": ID_INEXISTENTE}},
    ("POST", f"{API}/envios/cotizar"): {"json": {"direccion_id": ID_INEXISTENTE, "cantidad_prendas": 1}},
    ("POST", f"{API}/ia/eventos"): {"json": {"tipo_evento": "vista"}},
    ("POST", f"{API}/ia/voz"): {"json": {"texto": "camisa"}},
    ("POST", f"{API}/ia/recomendaciones"): {"json": {}},
}


def _peticion(http, metodo: str, plantilla: str, headers: dict | None, codigo: str = "tienda-a"):
    """Una petición MÍNIMA e inofensiva a `plantilla`: ids inexistentes y cuerpo vacío. El 403 de
    suscripción y el de plan llegan antes que cualquier 404 o 422, así que basta."""
    valores = {p: inexistente_para(p) for p in parametros_de(plantilla)}
    valores.update(codigo=codigo, pasarela="libelula", id_transaccion="TXN-INEXISTENTE")
    argumentos: dict = {"headers": headers or {}}
    if (metodo, plantilla) in ARCHIVOS:
        argumentos["files"] = ARCHIVOS[(metodo, plantilla)]
    elif (metodo, plantilla) in PETICIONES_VALIDAS:
        argumentos.update(PETICIONES_VALIDAS[(metodo, plantilla)])
    elif metodo in ("POST", "PUT"):
        argumentos["json"] = {}
    return http.request(metodo, armar(plantilla, valores), **argumentos)


def _es_error_de_plan(respuesta) -> bool:
    return respuesta.status_code == 403 and _json(respuesta).get("codigo") == "plan_no_incluye_funcionalidad"


def _es_error_de_suscripcion(respuesta) -> bool:
    return respuesta.status_code == 403 and _json(respuesta).get("codigo") == "suscripcion_no_activa"


def _ok(respuesta, esperados=(200, 201, 204)):
    assert respuesta.status_code in esperados, f"{respuesta.request.method} {respuesta.request.url.path}: {respuesta.status_code} {respuesta.text[:300]}"
    return respuesta.json() if respuesta.content else None


def _rutas(clase: str, con_funcionalidad: str | None = None) -> list[tuple[str, str]]:
    return sorted(
        clave
        for clave, ruta in RUTAS.items()
        if ruta.clase == clase and ruta.cobertura == MATRIZ and (con_funcionalidad is None or ruta.funcionalidad == con_funcionalidad)
    )


# =================================================================================================
# a) Tabla de verdad funcionalidad x plan
# =================================================================================================

RUTAS_POR_FUNCIONALIDAD = {
    f: sorted(clave for clave, ruta in RUTAS.items() if ruta.funcionalidad == f) for f in FUNCIONALIDADES
}
# Funcionalidad -> etapa que debe agregar sus rutas. Vacío desde la E22: las 8 funcionalidades ya tienen rutas
# (la E22 agregó las 4 de `/copias-seguridad`) y la tabla de verdad se ejecuta completa, con la POST real.
ETAPA_QUE_AGREGA_LA_RUTA: dict[str, str] = {}


def test_las_ocho_funcionalidades_son_las_del_contrato():
    assert len(FUNCIONALIDADES) == 8
    assert set(FUNCIONALIDADES) == {
        "gestion_productos", "gestion_ventas", "reservas", "reportes_convencionales",
        "reportes_ia", "operacion_offline", "analitica_ml", "copias_seguridad",
    }


def test_el_registro_no_declara_funcionalidades_desconocidas():
    declaradas = {r.funcionalidad for r in RUTAS.values() if r.funcionalidad}
    assert declaradas <= set(FUNCIONALIDADES), f"funcionalidades fuera de core.planes: {declaradas - set(FUNCIONALIDADES)}"


@pytest.mark.parametrize("plan", ["profesional", "basico"])
@pytest.mark.parametrize("funcionalidad", FUNCIONALIDADES)
def test_tabla_de_verdad_funcionalidad_por_plan(mundo, http, fabrica, funcionalidad, plan):
    rutas = RUTAS_POR_FUNCIONALIDAD[funcionalidad]
    if not rutas:
        pytest.skip(
            f"'{funcionalidad}' aún no tiene ruta en RUTAS: {ETAPA_QUE_AGREGA_LA_RUTA.get(funcionalidad, 'una etapa futura')} "
            "debe quitar este skip y agregar sus rutas a rutas_esperadas.py"
        )
    empresa = mundo.a if plan == "profesional" else mundo.b
    # El plan de cada empresa se comprueba por la API, no se supone.
    suscripcion = _ok(http.get(f"{API}/mi-empresa/suscripcion", headers=empresa.admin))
    assert suscripcion["plan_codigo"] == plan
    incluida = bool(getattr(fabrica.plan_de(plan), funcionalidad))  # la bandera sale de la tabla `plan`
    assert (funcionalidad in suscripcion["funcionalidades"]) == incluida

    fallas = []
    for metodo, ruta in rutas:
        respuesta = _peticion(http, metodo, ruta, empresa.admin, empresa.codigo)
        if incluida and _es_error_de_plan(respuesta):
            fallas.append(f"{metodo} {ruta}: el plan {plan} SÍ incluye '{funcionalidad}' y la ruta respondió 403 de plan")
        if not incluida:
            esperado = {
                "detail": "plan_no_incluye_funcionalidad",
                "codigo": "plan_no_incluye_funcionalidad",
                "mensaje": "Su plan no incluye esta funcionalidad",
                "funcionalidad": funcionalidad,
                "plan": plan,
            }
            if not (respuesta.status_code == 403 and _json(respuesta) == esperado):
                fallas.append(f"{metodo} {ruta}: debía ser 403 de plan y fue {respuesta.status_code} {respuesta.text[:150]}")
    assert not fallas, "\n".join(fallas)


def test_el_plan_profesional_incluye_todo_y_el_basico_solo_apaga_lo_documentado(fabrica):
    """La tabla `plan` es la fuente de verdad: si un plan cambia de banderas, esta prueba obliga
    a revisar la tabla de verdad de arriba."""
    profesional, basico = fabrica.plan_de("profesional"), fabrica.plan_de("basico")
    assert all(getattr(profesional, f) for f in FUNCIONALIDADES)
    assert {f for f in FUNCIONALIDADES if not getattr(basico, f)} == {"reportes_ia", "analitica_ml", "copias_seguridad"}


# =================================================================================================
# b) Estados de la suscripción x clase de ruta
# =================================================================================================

ESTADOS = ["activa", "vencida_por_fecha", "suspendida", "cancelada", "sin_suscripcion", "empresa_inactiva"]
# estado que informa el 403 `suscripcion_no_activa` en cada caso
ESTADO_INFORMADO = {
    "vencida_por_fecha": "vencida",
    "suspendida": "suspendida",
    "cancelada": "sin_suscripcion",  # una cancelada ya no cuenta como suscripción vigente
    "sin_suscripcion": "sin_suscripcion",
}
CLASES_B = [POR_ID, LISTADO, CREA_O_ACCION, PROPIA, PUBLICA]


@pytest.fixture(scope="module")
def empresas_en_estado(fabrica) -> dict[str, EmpresaDePrueba]:
    """Una empresa descartable por estado, preparada UNA vez (solo se las consulta)."""
    empresas = {estado: fabrica.crear() for estado in ESTADOS}
    fabrica.cambiar_suscripcion(empresas["vencida_por_fecha"].id, fecha_inicio=AYER - dt.timedelta(days=30), fecha_vencimiento=AYER)
    fabrica.cambiar_suscripcion(empresas["suspendida"].id, estado="suspendida")
    fabrica.cambiar_suscripcion(empresas["cancelada"].id, estado="cancelada")
    fabrica.quitar_suscripciones(empresas["sin_suscripcion"].id)
    fabrica.desactivar(empresas["empresa_inactiva"].id)
    return empresas


def _rutas_de_negocio_de_clase(clase: str) -> list[tuple[str, str]]:
    """Las rutas de la clase que SÍ exigen suscripción (las exentas se prueban aparte)."""
    return [(m, r) for m, r in _rutas(clase) if not _es_exenta_de_suscripcion(r)]


def _problema(estado: str, clase: str, respuesta) -> str | None:
    cuerpo = _json(respuesta)
    if estado in ESTADO_INFORMADO:
        if not (_es_error_de_suscripcion(respuesta) and cuerpo.get("estado") == ESTADO_INFORMADO[estado]):
            return f"debía ser 403 suscripcion_no_activa/{ESTADO_INFORMADO[estado]} y fue {respuesta.status_code} {respuesta.text[:120]}"
    elif estado == "empresa_inactiva":
        # Documentado en CLAUDE.md: una empresa inactiva deja sin acceso a TODOS sus tokens (401) y su
        # tienda pública responde 404, igual que un código inexistente (no se revela que existe).
        esperado = 404 if clase == PUBLICA else 401
        if respuesta.status_code != esperado:
            return f"empresa inactiva: debía ser {esperado} y fue {respuesta.status_code} {respuesta.text[:120]}"
    else:  # activa: la suscripción no bloquea nada (puede haber 404, 422 o 403 de permiso por la petición mínima)
        if _es_error_de_suscripcion(respuesta):
            return f"una empresa con suscripción activa recibió suscripcion_no_activa: {respuesta.text[:120]}"
        if respuesta.status_code in (401, 500):
            return f"respuesta {respuesta.status_code} inesperada con la suscripción activa: {respuesta.text[:120]}"
    return None


@pytest.mark.parametrize("clase", CLASES_B)
@pytest.mark.parametrize("estado", ESTADOS)
def test_estado_de_suscripcion_por_clase_de_ruta(http, empresas_en_estado, estado, clase):
    empresa = empresas_en_estado[estado]
    rutas = _rutas_de_negocio_de_clase(clase)
    assert rutas, f"la clase {clase} no tiene rutas en el registro"
    fallas = []
    for metodo, ruta in rutas:
        problema = _problema(estado, clase, _peticion(http, metodo, ruta, empresa.headers, empresa.codigo))
        if problema:
            fallas.append(f"{metodo} {ruta}: {problema}")
    assert not fallas, f"{len(fallas)} de {len(rutas)} rutas {clase} con el estado '{estado}':\n  " + "\n  ".join(fallas)


def test_las_rutas_exentas_de_suscripcion_son_las_del_contrato():
    assert tuple(RUTAS_SIN_SUSCRIPCION) == PREFIJOS_EXENTOS_DE_SUSCRIPCION, (
        "core.planes.RUTAS_SIN_SUSCRIPCION cambió: revisa PREFIJOS_EXENTOS_DE_SUSCRIPCION y las pruebas de rutas exentas"
    )
    # Ninguna ruta de negocio (las 4 clases protegidas) cae en la lista de exentas, salvo /auth/yo (la sesión).
    exentas_de_negocio = sorted(
        f"{m} {r}" for clase in CLASES_DE_NEGOCIO for m, r in _rutas(clase) if _es_exenta_de_suscripcion(r) and r != f"{API}/auth/yo"
    )
    assert exentas_de_negocio == []


def _firmar_webhook(id_transaccion: str):
    cuerpo = json.dumps({"id_transaccion": id_transaccion, "estado": "aprobado"}).encode("utf-8")
    firma = hmac.new(SECRETO_LIBELULA.encode("utf-8"), cuerpo, hashlib.sha256).hexdigest()
    return {"content": cuerpo, "headers": {"Content-Type": "application/json", "x-signature": firma}}


@pytest.mark.parametrize("estado", ESTADOS)
def test_las_rutas_exentas_siguen_funcionando_con_cualquier_estado(http, empresas_en_estado, estado):
    empresa = empresas_en_estado[estado]
    inactiva = estado == "empresa_inactiva"
    # La empresa inactiva no entra por ninguna vía autenticada (401) ni muestra su tienda (404).
    entra = 401 if inactiva else 200
    fallas = []

    def comprobar(nombre, respuesta, esperado):
        esperados = esperado if isinstance(esperado, tuple) else (esperado,)
        if respuesta.status_code not in esperados or _es_error_de_suscripcion(respuesta):
            fallas.append(f"{nombre}: {respuesta.status_code} {respuesta.text[:120]} (esperado {esperados})")

    comprobar("GET /health", http.get("/health"), 200)

    login = http.post(f"{API}/auth/login", json={"empresa": empresa.codigo, "email": "admin@tienda.bo", "password": CLAVE})
    comprobar("POST /auth/login", login, 401 if inactiva else 200)
    comprobar("GET /auth/yo", http.get(f"{API}/auth/yo", headers=empresa.headers), entra)
    if login.status_code == 200:
        comprobar("POST /auth/refresh", http.post(f"{API}/auth/refresh", json={"refresh_token": login.json()["refresh_token"]}), 200)

    comprobar("GET /mi-empresa", http.get(f"{API}/mi-empresa", headers=empresa.headers), entra)
    mi_suscripcion = http.get(f"{API}/mi-empresa/suscripcion", headers=empresa.headers)
    comprobar("GET /mi-empresa/suscripcion", mi_suscripcion, entra)
    if mi_suscripcion.status_code == 200 and estado in ESTADO_INFORMADO:
        informado = mi_suscripcion.json()["estado"]
        if informado != ESTADO_INFORMADO[estado]:
            fallas.append(f"/mi-empresa/suscripcion informó '{informado}' y se esperaba '{ESTADO_INFORMADO[estado]}'")

    tiendas = http.get(f"{API}/public/tiendas", params={"q": empresa.codigo})
    comprobar("GET /public/tiendas", tiendas, 200)
    if tiendas.status_code == 200 and (empresa.codigo in [t["codigo"] for t in tiendas.json()]) != (estado == "activa"):
        fallas.append(f"/public/tiendas: la tienda en estado '{estado}' {'debía' if estado == 'activa' else 'no debía'} aparecer")

    tienda = http.get(f"{API}/public/{empresa.codigo}/tienda")
    comprobar("GET /public/{codigo}/tienda", tienda, 404 if inactiva else 200)
    if tienda.status_code == 200 and tienda.json()["disponible"] != (estado == "activa"):
        fallas.append(f"/public/{{codigo}}/tienda: disponible={tienda.json()['disponible']} con el estado '{estado}'")

    # Pagos que ya movieron dinero: el webhook y la pantalla QR resuelven la empresa por la
    # transacción, no por la sesión; una transacción que no existe es 404, nunca suscripcion_no_activa.
    comprobar("POST /pagos/webhook/libelula", http.post(f"{API}/pagos/webhook/libelula", **_firmar_webhook("TXN-INEXISTENTE")), 404)
    comprobar("GET /pagos/qr/{id}", http.get(f"{API}/pagos/qr/TXN-INEXISTENTE"), 404)
    comprobar("POST /pagos/qr/{id}/confirmar", http.post(f"{API}/pagos/qr/TXN-INEXISTENTE/confirmar"), 404)

    # Tareas de servicio (token de servicio, sin usuario ni empresa).
    comprobar("POST /tareas/expirar-reservas", http.post(f"{API}/tareas/expirar-reservas", headers=TOKEN_SERVICIO), 200)
    comprobar("POST /tareas/expirar-ventas-pendientes", http.post(f"{API}/tareas/expirar-ventas-pendientes", headers=TOKEN_SERVICIO), 200)
    assert not fallas, f"estado '{estado}':\n  " + "\n  ".join(fallas)


@pytest.mark.parametrize("estado", ESTADOS)
def test_el_superadministrador_no_se_afecta_por_el_estado_de_una_empresa(http, empresas_en_estado, superadmin, estado):
    empresa = empresas_en_estado[estado]
    assert _ok(http.get(f"{API}/auth/yo", headers=superadmin)) is not None
    ficha = _ok(http.get(f"{API}/plataforma/empresas/{empresa.id}", headers=superadmin))
    assert ficha["codigo"] == empresa.codigo and ficha["activo"] == (estado != "empresa_inactiva")
    _ok(http.get(f"{API}/plataforma/suscripciones", params={"empresa_id": empresa.id}, headers=superadmin))
    # En una ruta de negocio recibe el 403 del modo plataforma, nunca el de suscripción.
    negocio = http.get(f"{API}/categorias", headers=superadmin)
    assert negocio.status_code == 403 and not _es_error_de_suscripcion(negocio), negocio.text


def test_la_tarea_de_vencimiento_solo_persiste_lo_que_ya_estaba_vencido(http, fabrica):
    """Última de la sección b: persiste el estado `vencida` (el bloqueo ya funcionaba por fecha, sin ella)."""
    empresa = fabrica.crear()
    fabrica.cambiar_suscripcion(empresa.id, fecha_inicio=AYER - dt.timedelta(days=30), fecha_vencimiento=AYER)
    assert _es_error_de_suscripcion(http.get(f"{API}/categorias", headers=empresa.headers))  # antes de la tarea
    assert _ok(http.post(f"{API}/tareas/vencer-suscripciones", headers=TOKEN_SERVICIO))["vencidas"] >= 1
    respuesta = http.get(f"{API}/categorias", headers=empresa.headers)
    assert _es_error_de_suscripcion(respuesta) and _json(respuesta)["estado"] == "vencida"


# =================================================================================================
# c) Independencia entre empresas
# =================================================================================================


def _categoria(http, empresa, nombre: str) -> int:
    return _ok(http.post(f"{API}/categorias", json={"nombre": nombre}, headers=empresa.headers))["id"]


def _nombres_de_categorias(http, empresa) -> list[str]:
    return sorted(c["nombre"] for c in _ok(http.get(f"{API}/categorias", headers=empresa.headers)))


def _suscripcion_id(http, superadmin, empresa) -> int:
    filas = _ok(http.get(f"{API}/plataforma/suscripciones", params={"empresa_id": empresa.id}, headers=superadmin))
    vigentes = [f for f in filas if f["estado"] != "cancelada"]
    assert len(vigentes) == 1
    return vigentes[0]["id"]


def test_suspender_x_no_cambia_nada_en_y_ni_en_el_universo(mundo, http, fabrica, superadmin):
    x, y = fabrica.crear(), fabrica.crear()
    _categoria(http, x, "Datos de X")
    _categoria(http, y, "Datos de Y")
    antes = {"y": mundo.instantanea(y.id), "a": mundo.instantanea(mundo.a.id), "b": mundo.instantanea(mundo.b.id)}
    categorias_y = _nombres_de_categorias(http, y)

    _ok(http.put(f"{API}/plataforma/suscripciones/{_suscripcion_id(http, superadmin, x)}/estado", json={"estado": "suspendida"}, headers=superadmin))

    # X queda bloqueada...
    assert _es_error_de_suscripcion(http.get(f"{API}/categorias", headers=x.headers))
    assert _es_error_de_suscripcion(http.get(f"{API}/public/{x.codigo}/catalogo"))
    # ...y Y, A y B siguen operando y viendo exactamente lo suyo.
    assert _nombres_de_categorias(http, y) == categorias_y
    assert _categoria(http, y, "Nueva de Y")
    assert _ok(http.get(f"{API}/mi-empresa/suscripcion", headers=y.headers))["estado"] == "activa"
    assert http.get(f"{API}/public/{y.codigo}/catalogo").status_code == 200
    for universo in (mundo.a, mundo.b):
        assert http.get(f"{API}/productos", headers=universo.admin).status_code == 200
        assert http.get(f"{API}/public/{universo.codigo}/catalogo").status_code == 200
    despues = {"a": mundo.instantanea(mundo.a.id), "b": mundo.instantanea(mundo.b.id)}
    assert mundo.cambios(antes["a"], despues["a"]) == [] and mundo.cambios(antes["b"], despues["b"]) == []
    # Los datos de X no se perdieron: reactivar la devuelve a su estado.
    _ok(http.put(f"{API}/plataforma/suscripciones/{_suscripcion_id(http, superadmin, x)}/estado", json={"estado": "activa"}, headers=superadmin))
    assert "Datos de X" in _nombres_de_categorias(http, x)


def test_cambiar_el_plan_de_x_no_cambia_el_de_y(http, fabrica, superadmin):
    x, y = fabrica.crear("profesional"), fabrica.crear("profesional")
    suscripcion_y = _ok(http.get(f"{API}/mi-empresa/suscripcion", headers=y.headers))
    assert suscripcion_y["plan_codigo"] == "profesional" and "reportes_ia" in suscripcion_y["funcionalidades"]

    _ok(http.post(f"{API}/plataforma/suscripciones", json={"empresa_id": x.id, "plan_codigo": "basico"}, headers=superadmin))

    suscripcion_x = _ok(http.get(f"{API}/mi-empresa/suscripcion", headers=x.headers))
    assert suscripcion_x["plan_codigo"] == "basico" and "reportes_ia" not in suscripcion_x["funcionalidades"]
    assert suscripcion_x["max_sucursales"] == 2
    assert _ok(http.get(f"{API}/mi-empresa/suscripcion", headers=y.headers)) == suscripcion_y  # idéntica a antes
    # En la práctica: X perdió el reporte con IA, Y lo conserva.
    assert _es_error_de_plan(http.post(f"{API}/ia/reporte-voz", json={}, headers=x.headers))
    reporte_y = http.post(f"{API}/ia/reporte-voz", json={}, headers=y.headers)
    assert not _es_error_de_plan(reporte_y) and reporte_y.status_code == 422  # llega a validar el cuerpo
    # Y la suscripción de Y sigue siendo UNA sola y no cancelada.
    assert _suscripcion_id(http, superadmin, y)


def _ciudad(http, empresa) -> int:
    return _ok(http.post(f"{API}/ciudades", json={"nombre": "Ciudad de pruebas"}, headers=empresa.headers))["id"]


def _sucursal(http, empresa, ciudad_id: int, codigo: str):
    """`empresa` puede ser una descartable (EmpresaDePrueba) o un Universo (A o B)."""
    return http.post(
        f"{API}/sucursales",
        json={"ciudad_id": ciudad_id, "codigo": codigo, "nombre": f"Sucursal {codigo}", "direccion": "Calle"},
        headers=empresa.admin if hasattr(empresa, "admin") else empresa.headers,
    )


def test_llenar_el_cupo_de_x_no_impide_a_y_crear_la_suya(http, fabrica):
    x, y = fabrica.crear("basico"), fabrica.crear("basico")
    ciudad_x, ciudad_y = _ciudad(http, x), _ciudad(http, y)
    for codigo in ("X-1", "X-2"):
        _ok(_sucursal(http, x, ciudad_x, codigo))
    llena = _sucursal(http, x, ciudad_x, "X-3")
    assert llena.status_code == 409 and _json(llena)["codigo"] == "limite_plan_excedido"

    # Y no comparte el cupo de X: crea las suyas hasta SU límite (2), con el mismo código de sucursal.
    for codigo in ("X-1", "X-2"):
        assert _sucursal(http, y, ciudad_y, codigo).status_code == 201
    assert _ok(http.get(f"{API}/mi-empresa/suscripcion", headers=y.headers))["sucursales_activas"] == 2
    tercera_de_y = _sucursal(http, y, ciudad_y, "X-3")
    assert tercera_de_y.status_code == 409 and _json(tercera_de_y)["actual"] == 2  # contó solo las de Y, no las 4


def _tienda(http, codigo: str) -> dict | None:
    listado = _ok(http.get(f"{API}/public/tiendas", params={"q": codigo, "tamanio": 50}))
    return next((t for t in listado if t["codigo"] == codigo), None)


def test_renombrar_o_desactivar_x_no_altera_las_tiendas_de_y_ni_de_a_y_b(mundo, http, fabrica, superadmin):
    x, y = fabrica.crear(nombre="Boutique Equis"), fabrica.crear(nombre="Boutique Ye")
    tienda_y = _tienda(http, y.codigo)
    tienda_a, tienda_b = _tienda(http, mundo.a.codigo), _tienda(http, mundo.b.codigo)
    assert tienda_y and tienda_a and tienda_b
    assert set(tienda_y) == {"codigo", "nombre", "logo_url", "color_acento"}  # solo los 4 campos públicos

    # Renombrar X: cambia su nombre, nunca su código, y no toca las demás.
    _ok(http.put(f"{API}/plataforma/empresas/{x.id}", json={"nombre": "Boutique Equis Renovada"}, headers=superadmin))
    tienda_x = _tienda(http, x.codigo)
    assert tienda_x["nombre"] == "Boutique Equis Renovada" and tienda_x["codigo"] == x.codigo
    assert _tienda(http, y.codigo) == tienda_y

    # Desactivar X: desaparece de /public/tiendas y su tienda responde 404; las demás, intactas.
    assert http.delete(f"{API}/plataforma/empresas/{x.id}", headers=superadmin).status_code == 204
    assert _tienda(http, x.codigo) is None
    assert http.get(f"{API}/public/{x.codigo}/tienda").status_code == 404
    assert _tienda(http, y.codigo) == tienda_y
    assert _tienda(http, mundo.a.codigo) == tienda_a and _tienda(http, mundo.b.codigo) == tienda_b
    assert _ok(http.get(f"{API}/public/{y.codigo}/tienda"))["disponible"] is True
    assert _ok(http.get(f"{API}/categorias", headers=y.headers)) is not None  # Y sigue operando


# =================================================================================================
# d) Límites de sucursales
# =================================================================================================


def _llenar(http, empresa, cantidad: int, ciudad_id: int, prefijo: str = "L") -> list[int]:
    return [_ok(_sucursal(http, empresa, ciudad_id, f"{prefijo}-{i}"))["id"] for i in range(1, cantidad + 1)]


def test_basico_la_tercera_sucursal_activa_da_409_con_contexto(http, fabrica):
    x = fabrica.crear("basico")
    ciudad = _ciudad(http, x)
    _llenar(http, x, 2, ciudad)
    tercera = _sucursal(http, x, ciudad, "L-3")
    assert tercera.status_code == 409
    cuerpo = tercera.json()
    assert cuerpo["detail"] == cuerpo["codigo"] == "limite_plan_excedido"
    assert (cuerpo["recurso"], cuerpo["limite"], cuerpo["actual"], cuerpo["plan"]) == ("sucursales", 2, 2, "basico")
    assert len(_ok(http.get(f"{API}/sucursales", headers=x.headers))) == 2  # la rechazada no dejó nada


def test_el_limite_de_una_empresa_basica_no_es_el_de_una_profesional(http, fabrica):
    basica, profesional = fabrica.crear("basico"), fabrica.crear("profesional")
    ciudad_b, ciudad_p = _ciudad(http, basica), _ciudad(http, profesional)
    _llenar(http, basica, 2, ciudad_b)
    assert _sucursal(http, basica, ciudad_b, "L-3").status_code == 409
    _llenar(http, profesional, 10, ciudad_p)  # la profesional sí llega a 10
    onceava = _sucursal(http, profesional, ciudad_p, "L-11")
    assert onceava.status_code == 409
    assert (_json(onceava)["limite"], _json(onceava)["actual"], _json(onceava)["plan"]) == (10, 10, "profesional")
    assert _ok(http.get(f"{API}/mi-empresa/suscripcion", headers=profesional.headers))["sucursales_activas"] == 10


def test_se_cuentan_solo_las_sucursales_activas_de_su_empresa(mundo, http, fabrica):
    x = fabrica.crear("basico")
    ciudad = _ciudad(http, x)
    # A y B ya tienen sus propias sucursales activas: no cuentan para X.
    assert _ok(http.get(f"{API}/mi-empresa/suscripcion", headers=mundo.b.admin))["sucursales_activas"] >= 2
    primera, segunda = _llenar(http, x, 2, ciudad)
    assert _sucursal(http, x, ciudad, "L-3").status_code == 409

    # Desactivar una libera un cupo (borrado lógico): ya no cuenta...
    assert http.delete(f"{API}/sucursales/{segunda}", headers=x.headers).status_code == 204
    assert _ok(http.get(f"{API}/mi-empresa/suscripcion", headers=x.headers))["sucursales_activas"] == 1
    tercera = _sucursal(http, x, ciudad, "L-3")
    assert tercera.status_code == 201  # entra en el cupo liberado
    # ...y reactivar la desactivada cuando ya no hay cupo vuelve a dar 409.
    reactivar = http.put(f"{API}/sucursales/{segunda}", json={"activo": True}, headers=x.headers)
    assert reactivar.status_code == 409 and _json(reactivar)["codigo"] == "limite_plan_excedido"


def test_b_con_su_cupo_lleno_recibe_409_y_no_crea_nada(mundo, http):
    b = mundo.b
    suscripcion = _ok(http.get(f"{API}/mi-empresa/suscripcion", headers=b.admin))
    assert suscripcion["sucursales_activas"] == suscripcion["max_sucursales"] == 2, "el universo deja a B (Básico) con su cupo lleno"
    antes = mundo.instantanea(b.id)
    respuesta = _sucursal(http, b, b.ids["ciudad"], "B-EXTRA")
    assert respuesta.status_code == 409 and _json(respuesta)["codigo"] == "limite_plan_excedido"
    assert mundo.cambios(antes, mundo.instantanea(b.id)) == []


# =================================================================================================
# e) Formato de los tres errores funcionales
# =================================================================================================


def _provocar_suscripcion_no_activa(mundo, http, fabrica):
    x = fabrica.crear()
    fabrica.cambiar_suscripcion(x.id, estado="suspendida")
    return http.get(f"{API}/categorias", headers=x.headers)


def _provocar_plan_no_incluye(mundo, http, fabrica):
    return http.post(f"{API}/ia/reporte-voz", json={}, headers=mundo.b.admin)


def _provocar_limite(mundo, http, fabrica):
    x = fabrica.crear("basico")
    ciudad = _ciudad(http, x)
    _llenar(http, x, 2, ciudad)
    return _sucursal(http, x, ciudad, "L-3")


FORMATO_DE_ERRORES = [
    pytest.param(_provocar_suscripcion_no_activa, "suscripcion_no_activa", 403, {"estado"}, id="suscripcion_no_activa-403"),
    pytest.param(_provocar_plan_no_incluye, "plan_no_incluye_funcionalidad", 403, {"funcionalidad", "plan"}, id="plan_no_incluye_funcionalidad-403"),
    pytest.param(_provocar_limite, "limite_plan_excedido", 409, {"recurso", "limite", "actual", "plan"}, id="limite_plan_excedido-409"),
]


@pytest.mark.parametrize("provocar, codigo, estado_http, contexto", FORMATO_DE_ERRORES)
def test_formato_de_los_errores_funcionales(mundo, http, fabrica, provocar, codigo, estado_http, contexto):
    respuesta = provocar(mundo, http, fabrica)
    assert respuesta.status_code == estado_http, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["detail"] == cuerpo["codigo"] == codigo
    assert isinstance(cuerpo["mensaje"], str) and len(cuerpo["mensaje"].strip()) >= 10
    assert set(cuerpo) == {"detail", "codigo", "mensaje", *contexto}, f"campos de {codigo}: {sorted(cuerpo)}"
    assert "application/json" in respuesta.headers["content-type"]


# =================================================================================================
# f) Cobertura de compuertas: ninguna ruta de negocio queda sin plan sin que alguien lo decida
# =================================================================================================

# Grupos de rutas de negocio SIN compuerta de plan, cada uno con su razón. (métodos | None = todos,
# prefijos de ruta, razón). Una ruta nueva sin `funcionalidad` que no caiga aquí hace fallar la prueba:
# o se le pone compuerta, o se justifica aquí por escrito.
EXENTOS_DE_PLAN: list[tuple[tuple[str, ...] | None, tuple[str, ...], str]] = [
    (None, (f"{API}/auth/yo", f"{API}/clientes/perfil", f"{API}/empleados/yo", f"{API}/notificaciones", f"{API}/favoritos",
            f"{API}/dispositivos-push"),
     "perfil, sesión, avisos (y el teléfono que los recibe) y favoritos del propio usuario: base de toda cuenta, el plan no los distingue"),
    (None, (f"{API}/ciudades", f"{API}/sucursales", f"{API}/empleados"),
     "organización básica de toda empresa; el plan limita CUÁNTAS sucursales (409 limite_plan_excedido), no el módulo"),
    (None, (f"{API}/usuarios", f"{API}/roles", f"{API}/permisos"),
     "seguridad básica (usuarios, roles, permisos): cualquier empresa necesita administrar a su gente"),
    (None, (f"{API}/inventario", f"{API}/transferencias"),
     "inventario y transferencias son operación básica (las ventas descuentan stock); no hay columna de plan para ellos"),
    (("GET",), (f"{API}/categorias", f"{API}/colecciones", f"{API}/colores", f"{API}/materiales", f"{API}/tallas", f"{API}/temporadas", f"{API}/zonas-envio"),
     "lectura de maestros: la usan también el cliente y la tienda; solo la ESCRITURA exige gestion_productos o gestion_ventas"),
    (None, (f"{API}/catalogo",),
     "consulta y búsqueda del catálogo (CU-06): lo ven clientes y personal de cualquier plan"),
    (None, (f"{API}/clientes/direcciones",),
     "libreta de direcciones del cliente: parte de su cuenta, no de la gestión de ventas del plan"),
    (None, (f"{API}/envios/cotizar",),
     "acepta peticiones sin usuario (también existe bajo /public/{codigo}): una compuerta exigiría sesión"),
    (None, (f"{API}/ia/eventos", f"{API}/ia/recomendaciones", f"{API}/ia/voz"),
     "búsqueda por voz y recomendador (CU-20, CU-21): base del producto; el plan solo distingue reportes_ia (CU-23)"),
    (None, (f"{API}/probador",),
     "probador virtual (CU-10, CU-11): la tabla `plan` no tiene una columna para él; no es funcionalidad de plan"),
    (None, (f"{API}/bitacora",),
     "bitácora de auditoría (E06): la ven los administradores de cualquier plan; la tabla `plan` no tiene columna para ella"),
]


def _grupo_de(metodo: str, ruta: str):
    for metodos, prefijos, razon in EXENTOS_DE_PLAN:
        if (metodos is None or metodo in metodos) and any(ruta == p or ruta.startswith(p + "/") for p in prefijos):
            return razon
    return None


RUTAS_DE_NEGOCIO = sorted(
    clave for clave, ruta in RUTAS.items() if ruta.clase in CLASES_DE_NEGOCIO and ruta.cobertura == MATRIZ
)


def test_toda_ruta_de_negocio_declara_su_funcionalidad_o_esta_exenta_con_razon():
    sin_decidir = [
        f"{m} {r}" for m, r in RUTAS_DE_NEGOCIO if not RUTAS[(m, r)].funcionalidad and _grupo_de(m, r) is None
    ]
    assert not sin_decidir, (
        f"{len(sin_decidir)} ruta(s) de negocio sin compuerta de plan y sin exención justificada:\n  "
        + "\n  ".join(sin_decidir)
        + "\nO se le pone `exigir_funcionalidad(...)` (y se declara en rutas_esperadas.py), o se agrega a "
        "EXENTOS_DE_PLAN en este archivo con la razón por escrito."
    )


def test_una_ruta_con_compuerta_no_figura_como_exenta():
    contradictorias = [
        f"{m} {r} ({RUTAS[(m, r)].funcionalidad})"
        for m, r in RUTAS_DE_NEGOCIO
        if RUTAS[(m, r)].funcionalidad and _grupo_de(m, r) is not None
    ]
    assert not contradictorias, f"rutas con compuerta de plan que además están en EXENTOS_DE_PLAN: {contradictorias}"


@pytest.mark.parametrize("indice", range(len(EXENTOS_DE_PLAN)), ids=[f"grupo-{i + 1}" for i in range(len(EXENTOS_DE_PLAN))])
def test_cada_grupo_exento_tiene_razon_y_rutas_vivas(indice):
    metodos, prefijos, razon = EXENTOS_DE_PLAN[indice]
    assert len(razon.strip()) >= 40, "la razón de una exención debe explicarse (mínimo 40 caracteres)"
    vivas = [
        (m, r) for m, r in RUTAS_DE_NEGOCIO
        if (metodos is None or m in metodos) and any(r == p or r.startswith(p + "/") for p in prefijos)
    ]
    assert vivas, f"el grupo {prefijos} no coincide con ninguna ruta de negocio: sobra en EXENTOS_DE_PLAN"


def test_las_compuertas_declaradas_cubren_las_funcionalidades_con_rutas():
    cubiertas = {r.funcionalidad for r in RUTAS.values() if r.funcionalidad}
    assert cubiertas == {
        "gestion_productos", "gestion_ventas", "reservas", "reportes_convencionales", "reportes_ia", "operacion_offline",
        "analitica_ml", "copias_seguridad",
    }, (
        "cambió el conjunto de funcionalidades con rutas: las 8 funcionalidades de `core.planes` tienen rutas desde la "
        "E22. Si agregas o quitas una compuerta, actualiza esta prueba y la tabla de verdad"
    )
    sin_compuerta = len(RUTAS_DE_NEGOCIO) - sum(1 for k in RUTAS_DE_NEGOCIO if RUTAS[k].funcionalidad)
    print(f"\nRutas de negocio: {len(RUTAS_DE_NEGOCIO)}; con compuerta: {len(RUTAS_DE_NEGOCIO) - sin_compuerta}; exentas justificadas: {sin_compuerta}")
