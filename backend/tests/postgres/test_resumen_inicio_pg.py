"""El resumen de la pantalla de inicio (`GET /api/v1/inicio/resumen`) y los índices de consulta contra PostgreSQL real:
las sumas, el agrupado y el filtro por rango de fechas se comportan distinto que en SQLite, y la migración
`a3c7e9d1b542` solo se puede probar aquí."""

from decimal import Decimal

import pytest
from sqlalchemy import text

from app.plataforma.repository import UsuarioRepository
from app.plataforma.schemas import UsuarioCrear
from tests.postgres.conftest import CLAVE, ejecutar_alembic

RESUMEN = "/api/v1/inicio/resumen"
INDICES = (
    "ix_venta_empresa_sucursal_fecha",
    "ix_venta_cliente",
    "ix_venta_detalle_venta",
    "ix_pago_venta",
    "ix_devolucion_venta",
    "ix_devolucion_detalle_devolucion",
    "ix_reserva_empresa_sucursal_visita",
    "ix_notificacion_usuario",
    "ix_movimiento_inventario_variante_sucursal",
    "ix_transaccion_pasarela_referencia",
)


def _cajero(client_pg, fabrica_pg, admin_pg, escenario) -> dict:
    """Un cajero empleado de la sucursal (el administrador no es empleado y no puede vender en caja)."""
    with fabrica_pg() as db:
        repo = UsuarioRepository()
        usuario = repo.crear(
            db, UsuarioCrear(nombre="Caja", apellido="Inicio", email="cajero-inicio@example.com", password=CLAVE)
        )
        repo.asignar_roles(db, usuario, ["cajero"])
        usuario_id = usuario.id
    respuesta = client_pg.post(
        "/api/v1/empleados",
        json={"usuario_id": usuario_id, "sucursal_id": escenario["sucursal_id"], "cargo": "Cajero"},
        headers=admin_pg,
    )
    assert respuesta.status_code == 201, respuesta.text
    token = client_pg.post(
        "/api/v1/auth/login", json={"empresa": "fashionstore", "email": "cajero-inicio@example.com", "password": CLAVE}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _vender(client_pg, cajero, escenario, *, cantidad: int, cobrar: bool = True) -> dict:
    venta = client_pg.post(
        "/api/v1/ventas/presencial",
        json={
            "sucursal_id": escenario["sucursal_id"],
            "detalle": [{"variante_id": escenario["variantes"][0], "cantidad": cantidad}],
        },
        headers=cajero,
    )
    assert venta.status_code == 201, venta.text
    if cobrar:
        pago = client_pg.post(
            "/api/v1/pagos/caja", json={"venta_id": venta.json()["id"], "metodo_pago": "qr"}, headers=cajero
        )
        assert pago.status_code == 201, pago.text
    return venta.json()


def test_el_resumen_suma_lo_cobrado_lo_pendiente_y_las_prendas_mas_vendidas(client_pg, fabrica_pg, admin_pg, escenario):
    cajero = _cajero(client_pg, fabrica_pg, admin_pg, escenario)
    _vender(client_pg, cajero, escenario, cantidad=2)
    _vender(client_pg, cajero, escenario, cantidad=1)
    _vender(client_pg, cajero, escenario, cantidad=1, cobrar=False)

    respuesta = client_pg.get(RESUMEN, headers=admin_pg)

    assert respuesta.status_code == 200, respuesta.text
    resumen = respuesta.json()
    assert resumen["sucursal_id"] is None and resumen["sucursal_nombre"] == "Todas las sucursales"
    ventas = resumen["ventas"]
    assert ventas["tickets"] == 2 and Decimal(ventas["total_ventas"]) == Decimal("300.00")
    assert ventas["por_cobrar_cantidad"] == 1 and Decimal(ventas["por_cobrar_total"]) == Decimal("100.00")
    assert ventas["mas_vendidas"] == [
        {"variante_id": escenario["variantes"][0], "nombre": "Camisa PostgreSQL", "cantidad": 3}
    ]
    assert [v["estado"] for v in ventas["recientes"]] == ["pendiente_pago", "pagada", "pagada"]
    assert all(v["fecha"].endswith("Z") for v in ventas["recientes"])


def test_sin_ventas_hoy_el_resumen_viene_en_ceros(client_pg, admin_pg, escenario):
    ventas = client_pg.get(RESUMEN, headers=admin_pg).json()["ventas"]

    assert ventas["tickets"] == 0 and Decimal(ventas["total_ventas"]) == 0
    assert ventas["mas_vendidas"] == [] and ventas["recientes"] == []


def test_los_indices_de_consulta_existen_en_la_base(client_pg, engine_pg):
    with engine_pg.begin() as conexion:
        existentes = {f[0] for f in conexion.execute(text("SELECT indexname FROM pg_indexes WHERE schemaname = current_schema()"))}

    assert set(INDICES) <= existentes


def test_la_migracion_de_indices_se_puede_bajar_y_volver_a_subir(url_pg, client_pg, engine_pg):
    engine_pg.dispose()  # sin conexiones abiertas que bloqueen el DDL de alembic
    try:
        bajada = ejecutar_alembic(url_pg, "downgrade", "b6d1f3a8c725")
        assert bajada.returncode == 0, bajada.stderr
        with engine_pg.begin() as conexion:
            existentes = {f[0] for f in conexion.execute(text("SELECT indexname FROM pg_indexes WHERE schemaname = current_schema()"))}
        assert not set(INDICES) & existentes
    finally:
        engine_pg.dispose()
        subida = ejecutar_alembic(url_pg, "upgrade", "head")
        assert subida.returncode == 0, subida.stderr
    with engine_pg.begin() as conexion:
        existentes = {f[0] for f in conexion.execute(text("SELECT indexname FROM pg_indexes WHERE schemaname = current_schema()"))}
    assert set(INDICES) <= existentes


@pytest.mark.parametrize("indice", INDICES)
def test_cada_indice_declarado_en_los_modelos_es_el_de_la_migracion(indice):
    from app.core.database import Base

    declarados = {i.name for tabla in Base.metadata.tables.values() for i in tabla.indexes}

    assert indice in declarados
