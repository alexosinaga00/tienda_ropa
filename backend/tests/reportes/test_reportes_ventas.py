"""BE-003: los reportes de ventas solo cuentan lo efectivamente vendido
(pagada/entregada), nunca ventas pendientes de pago ni anuladas."""

import datetime as dt

import pytest
from sqlalchemy import text

from app.core.deps import ParametrosPeriodo
from app.ventas import politicas as ventas_politicas
from app.ventas.repository import VW_VENTAS_DETALLE_SQL
from tests.ventas.test_ventas import _pagar_en_caja, _payload_presencial, contexto  # noqa: F401


@pytest.fixture()
def periodo(db_session) -> ParametrosPeriodo:
    # conftest solo crea la vista de inventario; esta la necesitan los reportes.
    db_session.execute(text(VW_VENTAS_DETALLE_SQL))
    db_session.commit()
    hoy = dt.date.today()
    return ParametrosPeriodo(desde=hoy - dt.timedelta(days=1), hasta=hoy + dt.timedelta(days=1))


def test_reportes_de_ventas_ignoran_pendientes_y_anuladas(client, cliente_headers, contexto, db_session, periodo):
    # 1) pagada: 1 unidad a 100.00 (costo 10.00)
    pagada = client.post("/api/v1/ventas/presencial", json=_payload_presencial(contexto), headers=contexto["cajero_headers"]).json()
    assert _pagar_en_caja(client, contexto["cajero_headers"], pagada["id"]).status_code == 201
    # 2) pendiente de pago: 2 unidades, nunca se cobró
    client.post("/api/v1/ventas/presencial", json=_payload_presencial(contexto, cantidad=2), headers=contexto["cajero_headers"])
    # 3) anulada: compra digital cancelada por el cliente
    client.post("/api/v1/carrito", json={"variante_id": contexto["variante_id"], "cantidad": 3}, headers=cliente_headers)
    digital = client.post("/api/v1/ventas/digital", json={"sucursal_id": contexto["sucursal_id"]}, headers=cliente_headers).json()
    assert client.post(f"/api/v1/pagos/venta/{digital['id']}/cancelar", headers=cliente_headers).status_code == 200

    resumen = ventas_politicas.reporte_ventas_resumen(db_session, periodo)
    assert resumen["transacciones"] == 1
    assert float(resumen["total_ventas"]) == 100.0
    assert float(resumen["margen_bruto"]) == 90.0

    top = ventas_politicas.reporte_ventas_top_productos(db_session, periodo)
    assert [int(fila["cantidad_vendida"]) for fila in top] == [1]
    canales = {fila["canal"]: int(fila["transacciones"]) for fila in ventas_politicas.reporte_ventas_por_canal(db_session, periodo)}
    assert canales == {"presencial": 1}
    assert len(ventas_politicas.reporte_ventas_detalle(db_session, periodo)) == 1
