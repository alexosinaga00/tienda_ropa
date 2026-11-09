"""Modelo multitenant (E01): clasificación de TODAS las tablas, llaves únicas
por empresa, correo, suscripción y plan.

`test_clasificacion_completa` obliga a clasificar toda tabla nueva: si alguien
agrega una tabla sin `empresa_id` y sin ponerla en GLOBALES, RAIZ o HEREDA, la
prueba falla (protege a las etapas que agregan tablas).
"""

import ast
import datetime as dt
import decimal
from pathlib import Path

import pytest
from sqlalchemy import Boolean, Date, DateTime, Integer, Numeric, String, Time, UniqueConstraint, func, insert, select
from sqlalchemy.exc import IntegrityError

import app.main  # noqa: F401  (registra todos los modelos)
from app.core.database import Base
from app.plataforma.models import Plan, Suscripcion
from scripts.seed_planes import PLANES, sembrar_planes
from tests.conftest import crear_empresa

# ---- Clasificación (sección 4.1 de E01) -----------------------------------

GLOBALES = {
    "rol", "permiso", "rol_permiso", "tipo_movimiento",
    "estado_reserva", "estado_venta", "metodo_pago", "estado_pago",
    "plan",
}
RAIZ = {"empresa"}
HEREDA = {"usuario_rol"}
# E06: la bitácora lleva `empresa_id` NULL permitido y SIN índice propio (sus
# índices compuestos empiezan por empresa_id) y no hereda el mixin: se filtra
# de forma explícita en BitacoraRepository.
BITACORA = "bitacora"
# E07: `operacion_sync` es de empresa (EmpresaMixin, NOT NULL), pero como `bitacora` no está en
# las 50 de la sección 4.1 de E01: se cuenta aparte.
OPERACION_SYNC = "operacion_sync"
# E11: `modelo_ml` (modelos de Machine Learning por empresa) también es de empresa (EmpresaMixin,
# NOT NULL) y se cuenta aparte, como `bitacora` y `operacion_sync`.
MODELO_ML = "modelo_ml"
# E22: `copia_seguridad` (historial de las copias de seguridad de una empresa) es de empresa (EmpresaMixin,
# NOT NULL) y se cuenta aparte.
COPIA_SEGURIDAD = "copia_seguridad"
# PayPal guardado y pedido sin conexión (CU-18 y CU-13): `metodo_pago_guardado` y `pedido_diferido` son de empresa
# (EmpresaMixin, NOT NULL) y se cuentan aparte.
METODO_PAGO_GUARDADO = "metodo_pago_guardado"
PEDIDO_DIFERIDO = "pedido_diferido"
# Notificaciones push (FCM): `dispositivo_push` también es de empresa (EmpresaMixin, NOT NULL) y se cuenta aparte.
DISPOSITIVO_PUSH = "dispositivo_push"
# Reembolsos (CU-17 y CU-18): `reembolso` (el dinero devuelto a quien compró) es de empresa (EmpresaMixin, NOT NULL) y se
# cuenta aparte.
REEMBOLSO = "reembolso"
# Cierre de caja (E21): `caja_turno` (el turno del cajón de una sucursal) también es de empresa (EmpresaMixin, NOT NULL).
CAJA_TURNO = "caja_turno"
# Contratación de planes: `pedido_contratacion` es global y SIN `empresa_id` (quien compra aún no tiene empresa; la
# empresa que se crea se enlaza en `empresa_creada_id`). Se trata como `plan`: sin pertenencia a una empresa.
PEDIDO_CONTRATACION = "pedido_contratacion"
SIN_EMPRESA = {PEDIDO_CONTRATACION}

# Las 50 tablas EMPRESA de la sección 4.1 (49 con empresa_id NOT NULL más
# `usuario`, que lo admite NULL: NULL = superadministrador).
EMPRESA_4_1 = {
    # plataforma (7)
    "usuario", "cliente", "notificacion", "ciudad", "sucursal", "horario_sucursal", "empleado",
    # catalogo (23)
    "categoria", "talla", "color", "material", "temporada", "coleccion", "producto",
    "producto_variante", "producto_imagen", "tabla_medida", "favorito", "stock",
    "movimiento_inventario", "transferencia", "transferencia_detalle", "proveedor",
    "producto_proveedor", "orden_compra", "orden_compra_detalle", "recepcion",
    "recepcion_detalle", "activo_probador", "probador_generacion",
    # comercial (17)
    "reserva", "reserva_detalle", "reserva_historial", "promocion", "promocion_alcance",
    "venta", "venta_detalle", "carrito", "carrito_detalle", "devolucion",
    "devolucion_detalle", "pago", "transaccion_pasarela", "zona_envio",
    "regla_tarifa_envio", "direccion_cliente", "envio",
    # inteligencia (3)
    "consulta_voz", "historial_navegacion", "recomendacion",
}
GLOBALES_4_1 = GLOBALES - {"plan"}  # las 8 del sistema


def _con_empresa_id() -> set[str]:
    return {t.name for t in Base.metadata.sorted_tables if "empresa_id" in t.c}


def test_clasificacion_completa():
    sin_clasificar = []
    for tabla in Base.metadata.sorted_tables:
        pertenencias = [
            tabla.name in GLOBALES,
            tabla.name in RAIZ,
            tabla.name in HEREDA,
            tabla.name in SIN_EMPRESA,
            "empresa_id" in tabla.c,
        ]
        if sum(pertenencias) != 1:
            sin_clasificar.append((tabla.name, pertenencias))
    assert not sin_clasificar, (
        "Cada tabla debe estar en exactamente uno de GLOBALES, RAIZ, HEREDA, SIN_EMPRESA o llevar "
        f"empresa_id (hereda EmpresaMixin). Sin clasificar o ambiguas: {sin_clasificar}"
    )


def test_los_conjuntos_coinciden_con_la_seccion_4_1():
    assert len(EMPRESA_4_1) == 50
    assert len(GLOBALES_4_1) == 8
    assert len(HEREDA) == 1
    assert len(EMPRESA_4_1) + len(GLOBALES_4_1) + len(HEREDA) == 59

    nombres = {t.name for t in Base.metadata.sorted_tables}
    # 59 tablas del primer parcial + empresa, plan, suscripcion + bitacora (E06) + operacion_sync (E07)
    # + modelo_ml (E11) + copia_seguridad (E22) + pedido_contratacion (contratación de planes, sin empresa_id)
    # + metodo_pago_guardado y pedido_diferido (PayPal guardado y pedido sin conexión) + dispositivo_push (push)
    # + reembolso (el dinero devuelto a quien compró) + caja_turno (el turno del cajón de una sucursal).
    assert nombres == EMPRESA_4_1 | GLOBALES_4_1 | HEREDA | SIN_EMPRESA | {
        "empresa", "plan", "suscripcion", BITACORA, OPERACION_SYNC, MODELO_ML, COPIA_SEGURIDAD,
        METODO_PAGO_GUARDADO, PEDIDO_DIFERIDO, DISPOSITIVO_PUSH, REEMBOLSO, CAJA_TURNO,
    }  # fmt: skip
    assert len(nombres) == 72
    # Las que llevan empresa_id: las 50 EMPRESA más suscripcion, bitacora, operacion_sync, modelo_ml, copia_seguridad,
    # metodo_pago_guardado, pedido_diferido, dispositivo_push, reembolso y caja_turno.
    assert _con_empresa_id() == EMPRESA_4_1 | {
        "suscripcion", BITACORA, OPERACION_SYNC, MODELO_ML, COPIA_SEGURIDAD, METODO_PAGO_GUARDADO, PEDIDO_DIFERIDO,
        DISPOSITIVO_PUSH, REEMBOLSO, CAJA_TURNO,
    }  # fmt: skip
    assert len(_con_empresa_id()) == 60


def test_empresa_id_es_not_null_salvo_en_usuario_y_apunta_a_empresa():
    for nombre in _con_empresa_id():
        columna = Base.metadata.tables[nombre].c.empresa_id
        assert columna.nullable == (nombre in ("usuario", BITACORA)), nombre
        assert [fk.target_fullname for fk in columna.foreign_keys] == ["empresa.id"], nombre
        if nombre == BITACORA:
            continue  # sus índices compuestos (empresa_id, ...) cubren la consulta por empresa
        assert columna.index, f"{nombre}: falta el índice ix_{nombre}_empresa_id"


# ---- Llaves únicas por empresa ---------------------------------------------

_TIEMPO = dt.time(9, 0)

# (tabla, nombre de la restricción, valores de las columnas únicas (sin empresa_id),
#  otras columnas que la fila necesita para cumplir sus CHECK)
UNICAS = [
    ("usuario", "uq_usuario_empresa_email", {"email": "dup@example.com"}, {}),
    ("sucursal", "uq_sucursal_empresa_codigo", {"codigo": "SUC1"}, {}),
    ("ciudad", "uq_ciudad_empresa_nombre_departamento", {"nombre": "Cochabamba", "departamento": "Cochabamba"}, {}),
    ("talla", "uq_talla_empresa_codigo", {"codigo": "XXL"}, {}),
    ("color", "uq_color_empresa_nombre", {"nombre": "Azul"}, {}),
    ("material", "uq_material_empresa_nombre", {"nombre": "Lino"}, {}),
    ("temporada", "uq_temporada_empresa_nombre_anio", {"nombre": "Invierno", "anio": 2026}, {}),
    ("producto", "uq_producto_empresa_codigo", {"codigo": "PROD1"}, {}),
    ("producto_variante", "uq_variante_empresa_sku", {"sku": "SKU-1"}, {}),
    ("producto_variante", "uq_variante_empresa_codigo_barras", {"codigo_barras": "7770001"}, {}),
    ("transferencia", "uq_transferencia_empresa_codigo", {"codigo": "TRF1"}, {}),
    ("proveedor", "uq_proveedor_empresa_nit", {"nit": "1020304050"}, {}),
    ("orden_compra", "uq_orden_compra_empresa_codigo", {"codigo": "OC1"}, {}),
    ("recepcion", "uq_recepcion_empresa_codigo", {"codigo": "REC1"}, {}),
    (
        "reserva",
        "uq_reserva_empresa_codigo",
        {"codigo": "RES1"},
        {"hora_visita_desde": _TIEMPO, "hora_visita_hasta": dt.time(10, 0)},
    ),
    ("venta", "uq_venta_empresa_codigo", {"codigo": "VEN1"}, {"canal": "digital"}),
    ("devolucion", "uq_devolucion_empresa_codigo", {"codigo": "DEV1"}, {}),
]


class _Filas:
    """Arma filas mínimas válidas con INSERT de Core (no pasa por el ORM, así
    que `empresa_id` se indica a mano). SQLite no valida las FK, por eso las
    columnas FK reciben un id cualquiera; todo valor que NO se pide repetir
    sale distinto en cada fila, para que solo choque la llave que se prueba."""

    def __init__(self, db):
        self.db = db
        self.n = 0

    def insertar(self, nombre_tabla: str, empresa_id: int | None, **valores) -> None:
        tabla = Base.metadata.tables[nombre_tabla]
        self.n += 1
        fila: dict = {}
        for posicion, col in enumerate(tabla.c):
            if col.name in valores:
                fila[col.name] = valores[col.name]
            elif col.name == "empresa_id":
                fila[col.name] = empresa_id
            elif col.primary_key or col.nullable or col.default is not None or col.server_default is not None:
                continue
            elif col.foreign_keys:
                fila[col.name] = self.n * 100 + posicion
            elif isinstance(col.type, Boolean):
                fila[col.name] = True
            elif isinstance(col.type, String):
                fila[col.name] = f"v{self.n}x{posicion}"[: col.type.length or 20]
            elif isinstance(col.type, Integer):
                fila[col.name] = self.n
            elif isinstance(col.type, Numeric):
                fila[col.name] = decimal.Decimal("1.00")
            elif isinstance(col.type, DateTime):
                fila[col.name] = dt.datetime(2026, 1, 1, 12, 0)
            elif isinstance(col.type, Date):
                fila[col.name] = dt.date(2026, 1, 1)
            elif isinstance(col.type, Time):
                fila[col.name] = _TIEMPO
            else:  # pragma: no cover - una columna nueva obliga a extender el helper
                raise AssertionError(f"{nombre_tabla}.{col.name}: tipo {col.type!r} sin valor de prueba")
        self.db.execute(insert(tabla).values(**fila))

    def chocar(self, nombre_tabla: str, empresa_id: int | None, **valores) -> str:
        """Inserta esperando IntegrityError (dentro de un SAVEPOINT) y devuelve el mensaje."""
        with pytest.raises(IntegrityError) as error:
            with self.db.begin_nested():
                self.insertar(nombre_tabla, empresa_id, **valores)
        return str(error.value)


@pytest.fixture()
def filas(db_session):
    return _Filas(db_session)


@pytest.mark.parametrize(("tabla", "restriccion", "unicos", "extras"), UNICAS, ids=[u[1] for u in UNICAS])
def test_llave_unica_por_empresa(db_session, filas, tabla, restriccion, unicos, extras):
    # Declaración: UniqueConstraint (empresa_id, ...) con ese nombre, y sin
    # `unique=True` suelto en las columnas (sería la llave global vieja).
    objeto = Base.metadata.tables[tabla]
    declarada = {c.name: c for c in objeto.constraints if isinstance(c, UniqueConstraint)}[restriccion]
    assert [c.name for c in declarada.columns] == ["empresa_id", *unicos]
    assert not [c.name for c in objeto.c if c.unique], f"{tabla}: queda una llave única global"

    otra = crear_empresa(db_session, "otra").id
    valores = {**unicos, **extras}
    filas.insertar(tabla, 1, **valores)
    # El mismo valor en OTRA empresa es válido...
    filas.insertar(tabla, otra, **valores)
    # ...y repetido en la MISMA empresa choca contra esa llave.
    mensaje = filas.chocar(tabla, 1, **valores)
    for columna in ("empresa_id", *unicos):
        assert f"{tabla}.{columna}" in mensaje, mensaje


def test_las_17_unicas_por_empresa_estan_en_el_modelo():
    assert len(UNICAS) == 17
    assert len({u[1] for u in UNICAS}) == 17
    assert len({u[0] for u in UNICAS}) == 16
    # Cada UniqueConstraint "por empresa" del modelo está cubierta por la lista.
    del_modelo = {
        c.name
        for t in Base.metadata.sorted_tables
        for c in t.constraints
        if isinstance(c, UniqueConstraint) and c.name and "empresa_id" in {x.name for x in c.columns}
    }
    # `operacion_sync` (E07) trae su propia única (empresa, operación) y su prueba está en
    # tests/sincronizacion; aquí solo se reconoce.
    assert del_modelo == {u[1] for u in UNICAS} | {
        "uq_operacion_sync_empresa_operacion",
        "uq_pedido_diferido_empresa_operacion",  # su prueba está en tests/comercial/test_pedido_diferido.py
        "uq_dispositivo_push_empresa_token",  # su prueba está en tests/plataforma/test_dispositivos_push.py
        "uq_modelo_ml_empresa_tipo_version",  # su prueba está en tests/inteligencia/ml/test_persistencia_modelo_ml.py
    }


# ---- Correo ----------------------------------------------------------------


def test_mismo_correo_en_dos_empresas_es_valido_y_repetido_en_una_no(db_session, filas):
    otra = crear_empresa(db_session, "otra").id
    filas.insertar("usuario", 1, email="mismo@example.com")
    filas.insertar("usuario", otra, email="mismo@example.com")
    assert "usuario.email" in filas.chocar("usuario", otra, email="mismo@example.com")


def test_dos_superadministradores_con_el_mismo_correo_chocan(db_session, filas):
    filas.insertar("usuario", None, email="super@example.com")
    mensaje = filas.chocar("usuario", None, email="super@example.com")
    assert "usuario.email" in mensaje, mensaje
    # Otro correo de superadministrador sí es válido, y el mismo correo de un
    # usuario de empresa también (el índice parcial solo mira empresa_id NULL).
    filas.insertar("usuario", None, email="super2@example.com")
    filas.insertar("usuario", 1, email="super@example.com")


# ---- Suscripción -----------------------------------------------------------

_HOY = dt.date(2026, 1, 1)
_SUSCRIPCION = Suscripcion.__table__


def _suscripcion(db, empresa_id: int, **cambios) -> None:
    datos = {
        "empresa_id": empresa_id,
        "plan_id": db.scalar(select(Plan.id).where(Plan.codigo == "basico")),
        "estado": "activa",
        "fecha_inicio": _HOY,
        "fecha_vencimiento": _HOY + dt.timedelta(days=30),
    }
    datos.update(cambios)
    db.execute(insert(_SUSCRIPCION).values(**datos))


def _chocar_suscripcion(db, empresa_id: int, **cambios) -> str:
    with pytest.raises(IntegrityError) as error:
        with db.begin_nested():
            _suscripcion(db, empresa_id, **cambios)
    return str(error.value)


def _cancelar_las_de(db, empresa_id: int) -> None:
    db.execute(_SUSCRIPCION.update().where(_SUSCRIPCION.c.empresa_id == empresa_id).values(estado="cancelada"))


def test_segunda_suscripcion_no_cancelada_de_la_misma_empresa_choca(db_session):
    # La empresa 1 ya tiene una activa (la siembra la fixture).
    for estado in ("activa", "vencida", "suspendida"):
        mensaje = _chocar_suscripcion(db_session, 1, estado=estado)
        assert "suscripcion.empresa_id" in mensaje, mensaje


def test_una_cancelada_y_una_activa_conviven(db_session):
    otra = crear_empresa(db_session, "otra").id
    _cancelar_las_de(db_session, otra)
    _suscripcion(db_session, otra, estado="activa")  # la nueva
    _suscripcion(db_session, otra, estado="cancelada")  # y más historial cancelado
    total = db_session.scalar(select(func.count()).select_from(_SUSCRIPCION).where(_SUSCRIPCION.c.empresa_id == otra))
    assert total == 3


def test_cada_empresa_tiene_su_propia_suscripcion_vigente(db_session):
    otra = crear_empresa(db_session, "otra").id
    vigentes = db_session.scalars(select(_SUSCRIPCION.c.empresa_id).where(_SUSCRIPCION.c.estado == "activa")).all()
    assert sorted(vigentes) == [1, otra]


def test_suscripcion_con_estado_invalido_choca(db_session):
    otra = crear_empresa(db_session, "otra").id
    _cancelar_las_de(db_session, otra)
    mensaje = _chocar_suscripcion(db_session, otra, estado="pagada")
    assert "ck_suscripcion_estado" in mensaje or "CHECK" in mensaje, mensaje


def test_suscripcion_con_vencimiento_anterior_al_inicio_choca(db_session):
    otra = crear_empresa(db_session, "otra").id
    _cancelar_las_de(db_session, otra)
    mensaje = _chocar_suscripcion(db_session, otra, fecha_vencimiento=_HOY - dt.timedelta(days=1))
    assert "ck_suscripcion_fechas" in mensaje or "CHECK" in mensaje, mensaje
    # El mismo día de inicio sí es válido (>=).
    _suscripcion(db_session, otra, fecha_vencimiento=_HOY)


# ---- Plan -------------------------------------------------------------------


def test_plan_codigo_es_unico(db_session):
    with pytest.raises(IntegrityError) as error:
        with db_session.begin_nested():
            db_session.execute(insert(Plan.__table__).values(**PLANES[0]))
    assert "plan.codigo" in str(error.value)


def test_los_planes_sembrados_tienen_los_limites_del_enunciado(db_session):
    planes = {p.codigo: p for p in db_session.scalars(select(Plan))}
    assert set(planes) == {"basico", "profesional"}
    assert planes["basico"].max_sucursales == 2
    assert planes["profesional"].max_sucursales == 10
    basico, profesional = planes["basico"], planes["profesional"]
    assert (basico.reportes_ia, basico.analitica_ml, basico.copias_seguridad) == (False, False, False)
    assert (profesional.reportes_ia, profesional.analitica_ml, profesional.copias_seguridad) == (True, True, True)
    assert (basico.max_copias_historial, profesional.max_copias_historial) == (0, 5)
    for plan in planes.values():
        assert plan.reportes_convencionales and plan.operacion_offline
        assert plan.gestion_productos and plan.gestion_ventas and plan.reservas
        assert plan.plazo_cambio_horas_defecto == 24


def test_sembrar_planes_es_idempotente_y_actualiza(db_session):
    antes = db_session.scalar(select(Plan.id).where(Plan.codigo == "basico"))
    plan = db_session.scalar(select(Plan).where(Plan.codigo == "basico"))
    plan.max_sucursales = 99  # alguien lo cambió a mano
    db_session.flush()

    devueltos = sembrar_planes(db_session)

    assert set(devueltos) == {"basico", "profesional"}
    assert db_session.scalar(select(Plan.id).where(Plan.codigo == "basico")) == antes
    assert db_session.scalar(select(Plan.max_sucursales).where(Plan.codigo == "basico")) == 2
    assert db_session.scalar(select(func.count()).select_from(Plan.__table__)) == 2


# ---- seed_planes.PLANES == literales de la migración -------------------------

_VERSIONES = Path(__file__).resolve().parents[2] / "alembic" / "versions"


def _literal_de_la_migracion(nombre: str):
    """Valor de la constante `nombre` de la migración multitenant, leída del
    ARCHIVO (se evalúa solo el literal; no se importa la migración)."""
    archivos = sorted(_VERSIONES.glob("*multitenant*.py"))
    assert len(archivos) == 1, f"Se esperaba una sola migración multitenant, hay {archivos}"
    arbol = ast.parse(archivos[0].read_text(encoding="utf-8"))
    for nodo in arbol.body:
        if isinstance(nodo, ast.AnnAssign) and getattr(nodo.target, "id", None) == nombre:
            return ast.literal_eval(nodo.value)
        if isinstance(nodo, ast.Assign) and any(getattr(t, "id", None) == nombre for t in nodo.targets):
            return ast.literal_eval(nodo.value)
    raise AssertionError(f"La migración no define {nombre}")


def test_planes_del_seed_coinciden_con_los_literales_de_la_migracion():
    de_la_migracion = {p["codigo"]: p for p in _literal_de_la_migracion("PLANES")}
    del_seed = {p["codigo"]: p for p in PLANES}
    assert del_seed == de_la_migracion


def test_tablas_de_empresa_de_la_migracion_coinciden_con_la_seccion_4_1():
    de_la_migracion = _literal_de_la_migracion("TABLAS_EMPRESA")
    assert len(de_la_migracion) == len(set(de_la_migracion)) == 50
    assert set(de_la_migracion) == EMPRESA_4_1
