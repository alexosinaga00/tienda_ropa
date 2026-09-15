"""Corre la cadena de seeds real (catálogo -> operativo -> demo) sobre la base
de pruebas: valida que seed_demo respete las reglas de negocio (stock,
estados, costos) y que una segunda corrida no duplique nada."""

from sqlalchemy import func, select

from scripts import seed_demo, seed_operativo
from scripts.seed_catalogo import seed as seed_catalogo


def _preparar_catalogo(client, admin_headers, db_session):
    from app.catalogo.models import Talla

    seed_catalogo(db_session)
    tallas = {t.codigo: t.id for t in db_session.scalars(select(Talla))}
    color = client.post("/api/v1/colores", json={"nombre": "Negro"}, headers=admin_headers).json()
    for n, categoria in enumerate(["Poleras", "Chamarras"]):
        cat = client.post("/api/v1/categorias", json={"nombre": categoria}, headers=admin_headers).json()
        for i in range(3):
            respuesta = client.post(
                "/api/v1/productos",
                json={
                    "codigo": f"DEMO-{n}{i}",
                    "nombre": f"{categoria} demo {i}",
                    "categoria_id": cat["id"],
                    "precio_base": "149.00",
                    "genero": "hombre",
                    "tallas_ids": [tallas["L"], tallas["XL"]],
                    "colores_ids": [color["id"]],
                },
                headers=admin_headers,
            )
            assert respuesta.status_code == 201, respuesta.text


def _conteos(db):
    from app.catalogo.models import Coleccion, TablaMedida, Temporada
    from app.entregas.models import DireccionCliente, Envio
    from app.inteligencia.models import HistorialNavegacion
    from app.inventario.models import Transferencia
    from app.reservas.models import Reserva
    from app.seguridad.models import Cliente
    from app.ventas.models import Devolucion, Promocion, Venta

    modelos = [Temporada, Coleccion, TablaMedida, Cliente, DireccionCliente, Promocion, Transferencia, Venta,
               Envio, Devolucion, Reserva, HistorialNavegacion]
    return {m.__tablename__: db.scalar(select(func.count()).select_from(m)) for m in modelos}


def test_seed_demo_carga_datos_coherentes_y_es_idempotente(client, admin_headers, db_session, monkeypatch):
    from app.inventario.models import Stock
    from app.ventas.models import EstadoVenta, Venta, VentaDetalle

    _preparar_catalogo(client, admin_headers, db_session)
    seed_operativo.seed(db_session, ejecutar=True, password="claveDemo123")

    seed_demo.seed(db_session, ejecutar=True, password="claveDemo123")
    primera = _conteos(db_session)

    assert primera["cliente"] >= 10
    assert primera["direccion_cliente"] >= 10
    assert primera["promocion"] == 3
    assert primera["transferencia"] == 4
    assert primera["tabla_medida"] > 0
    assert primera["venta"] >= 20
    assert primera["envio"] >= 1
    assert primera["devolucion"] == 3
    assert primera["reserva"] == 5
    assert primera["historial_navegacion"] == 150

    # Coherencia: nada negativo, lo reservado nunca supera lo físico, toda
    # venta pagada tiene costo congelado en cada línea.
    for stock in db_session.scalars(select(Stock)):
        assert stock.cantidad_fisica >= 0
        assert 0 <= stock.cantidad_reservada <= stock.cantidad_fisica
    pagada = db_session.scalar(select(EstadoVenta.id).where(EstadoVenta.codigo == "pagada"))
    sin_costo = db_session.scalar(
        select(func.count())
        .select_from(VentaDetalle)
        .join(Venta, Venta.id == VentaDetalle.venta_id)
        .where(Venta.estado_id == pagada, VentaDetalle.costo_unitario.is_(None))
    )
    assert sin_costo == 0

    # Segunda corrida: no duplica.
    seed_demo.seed(db_session, ejecutar=True, password="claveDemo123")
    assert _conteos(db_session) == primera


def test_seed_demo_dry_run_no_escribe(client, admin_headers, db_session):
    _preparar_catalogo(client, admin_headers, db_session)
    seed_operativo.seed(db_session, ejecutar=True, password="claveDemo123")
    antes = _conteos(db_session)
    resumen = seed_demo.seed(db_session, ejecutar=False, password=None)
    assert _conteos(db_session) == antes
    assert resumen.creados["cliente"] == 10
