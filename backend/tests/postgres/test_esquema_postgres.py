"""Lo que SQLite no puede comprobar del esquema: que las migraciones dejan en
PostgreSQL exactamente lo que declaran los modelos, y que las piezas propias
de PostgreSQL (vistas, columna generada de stock) funcionan.
"""

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, text

from app.core.database import Base


def test_las_migraciones_dejan_el_esquema_igual_a_los_modelos(engine_pg):
    # Importa los modelos de todos los paquetes para que Base.metadata los vea.
    from app.catalogo import models as _c  # noqa: F401
    from app.comercial import models as _co  # noqa: F401
    from app.inteligencia import models as _i  # noqa: F401
    from app.plataforma import models as _p  # noqa: F401

    with engine_pg.connect() as conexion:
        diferencias = compare_metadata(MigrationContext.configure(conexion), Base.metadata)

    assert diferencias == [], f"Los modelos y las migraciones difieren: {diferencias}"


def test_el_modo_espejo_ya_no_existe_en_la_base(engine_pg):
    inspector = inspect(engine_pg)

    assert "sesion_probador" not in inspector.get_table_names()
    assert "anclajes" not in {c["name"] for c in inspector.get_columns("activo_probador")}


def test_las_vistas_se_crean_con_las_migraciones(engine_pg):
    vistas = set(inspect(engine_pg).get_view_names())

    assert {"vw_inventario_consolidado", "vw_ventas_detalle"} <= vistas


def test_cantidad_disponible_es_una_columna_generada(engine_pg, fabrica_pg, client_pg, admin_pg, escenario):
    variante_id = escenario["variantes"][0]
    sucursal_id = escenario["sucursal_id"]
    with fabrica_pg() as db:
        db.execute(
            text("UPDATE stock SET cantidad_reservada = 4 WHERE variante_id = :v AND sucursal_id = :s"),
            {"v": variante_id, "s": sucursal_id},
        )
        db.commit()
        fila = db.execute(
            text(
                "SELECT cantidad_fisica, cantidad_reservada, cantidad_disponible FROM stock "
                "WHERE variante_id = :v AND sucursal_id = :s"
            ),
            {"v": variante_id, "s": sucursal_id},
        ).one()

    assert tuple(fila) == (10, 4, 6)


def test_la_base_tiene_69_tablas_con_las_de_multitenant_la_bitacora_la_sincronizacion_el_ml_las_copias_la_contratacion_y_el_paypal_guardado(
    engine_pg,
):
    # 59 anteriores + empresa, plan y suscripcion + bitacora + operacion_sync + modelo_ml + copia_seguridad
    # + pedido_contratacion + metodo_pago_guardado + pedido_diferido (sin contar alembic_version).
    tablas = set(inspect(engine_pg).get_table_names()) - {"alembic_version"}

    assert len(tablas) == 69
    assert {
        "empresa", "plan", "suscripcion", "bitacora", "operacion_sync", "modelo_ml", "copia_seguridad",
        "pedido_contratacion", "metodo_pago_guardado", "pedido_diferido",
    } <= tablas  # fmt: skip
    guardados = {i["name"]: i for i in inspect(engine_pg).get_indexes("metodo_pago_guardado")}
    assert guardados["ux_metodo_pago_guardado_activo"]["unique"]
    assert "activo" in guardados["ux_metodo_pago_guardado_activo"]["dialect_options"]["postgresql_where"]
    indices = {i["name"]: i for i in inspect(engine_pg).get_indexes("copia_seguridad")}
    assert indices["ux_copia_en_proceso"]["unique"]
    assert "en_proceso" in indices["ux_copia_en_proceso"]["dialect_options"]["postgresql_where"]
    pedidos = {i["name"]: i for i in inspect(engine_pg).get_indexes("pedido_contratacion")}
    assert pedidos["ux_pedido_prueba_correo"]["unique"]
    assert "prueba" in pedidos["ux_pedido_prueba_correo"]["dialect_options"]["postgresql_where"]
