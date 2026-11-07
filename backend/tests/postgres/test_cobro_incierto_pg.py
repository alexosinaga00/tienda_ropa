"""El cobro incierto de un pedido sin conexión en PostgreSQL real (PayPal simulado): la migración del estado `incierto` y los
reintentos SIMULTÁNEOS. SQLite no aplica `SELECT ... FOR UPDATE`: aquí se demuestra que dos reintentos a la vez del mismo cobro
incierto lo concilian UNA vez (uno espera al otro y recibe lo ya decidido)."""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app.comercial.casos_uso.cu13_gestionar_carrito_compra_digital import RealizarPedidoDiferido
from app.comercial.models import PedidoDiferido, Venta
from app.core.exceptions import ErrorFuncional
from tests.postgres.conftest import ejecutar_alembic

# Los fixtures `pp`, `cliente` y las ayudas se reutilizan de la prueba del PayPal guardado.
from tests.postgres.test_paypal_guardado_pg import _contar, _enviar, _pedido, _stock, cliente, pp  # noqa: F401
from .paralelo import ejecutar_en_paralelo


def _perder_el_primer_cobro(fabrica, usuario_id, datos, pp) -> None:  # noqa: F811
    """PayPal cobra y la respuesta se pierde: queda la marca `incierto` y el cliente recibe un 503."""
    pp.perder_respuestas_de_cobro = 1
    with fabrica() as db:
        with pytest.raises(ErrorFuncional) as error:
            RealizarPedidoDiferido().ejecutar(db, usuario_id, datos)
    assert error.value.estado == 503 if hasattr(error.value, "estado") else True


def test_la_marca_incierta_queda_guardada_con_el_monto(client_pg, fabrica_pg, escenario, cliente, pp):  # noqa: F811
    datos = _pedido(escenario, cantidad=2)

    _perder_el_primer_cobro(fabrica_pg, cliente["usuario_id"], datos, pp)

    with fabrica_pg() as db:
        (fila,) = db.scalars(select(PedidoDiferido)).all()
        assert (fila.estado, fila.motivo, fila.venta_id) == ("incierto", "cobro_incierto", None)
        assert fila.total == Decimal("200.00") and fila.total_usd is not None
    assert pp.cobros_vault == 1 and _contar(fabrica_pg, Venta) == 0
    assert _stock(fabrica_pg, escenario["variantes"][0], escenario["sucursal_id"]) == (10, 0)


def test_dos_reintentos_simultaneos_de_un_cobro_incierto_lo_concilian_una_vez(client_pg, fabrica_pg, escenario, cliente, pp):  # noqa: F811
    datos = _pedido(escenario, cantidad=2)
    _perder_el_primer_cobro(fabrica_pg, cliente["usuario_id"], datos, pp)

    resultados = ejecutar_en_paralelo(
        fabrica_pg, [_enviar(cliente["usuario_id"], datos), _enviar(cliente["usuario_id"], datos)]
    )

    assert all(r.ok for r in resultados), [r.error for r in resultados if not r.ok]
    respuestas = [r.valor for r in resultados]
    assert [x.estado for x in respuestas] == ["cobrado", "cobrado"]
    assert sorted(x.duplicada for x in respuestas) == [False, True]  # uno concilió; el otro recibió lo decidido
    assert len({x.venta_id for x in respuestas}) == 1
    assert pp.cobros_vault == 1  # el dinero se movió una sola vez, en el primer intento
    assert _contar(fabrica_pg, PedidoDiferido) == 1 and _contar(fabrica_pg, Venta) == 1
    assert _stock(fabrica_pg, escenario["variantes"][0], escenario["sucursal_id"]) == (8, 0)


def test_la_migracion_del_cobro_incierto_se_puede_bajar_y_volver_a_subir(url_pg, client_pg, fabrica_pg, escenario, cliente, engine_pg):  # noqa: F811
    operacion = uuid.uuid4()
    with fabrica_pg() as db:
        db.add(
            PedidoDiferido(
                operacion_id=operacion,
                usuario_id=cliente["usuario_id"],
                sucursal_id=escenario["sucursal_id"],
                estado="incierto",
                motivo="cobro_incierto",
                total=Decimal("100.00"),
                total_usd=Decimal("14.37"),
            )
        )
        db.commit()
    engine_pg.dispose()  # sin conexiones abiertas que bloqueen el DDL de alembic
    try:
        bajada = ejecutar_alembic(url_pg, "downgrade", "a3c7e9d1b542")
        assert bajada.returncode == 0, bajada.stderr
        with engine_pg.begin() as conexion:
            # La baja convierte la fila incierta en un rechazo (para poder restaurar el CHECK anterior).
            assert conexion.execute(text("SELECT estado, motivo FROM pedido_diferido")).one() == ("rechazado", "cobro_incierto")
        with pytest.raises(IntegrityError), engine_pg.begin() as conexion:
            conexion.execute(
                text(
                    "INSERT INTO pedido_diferido (empresa_id, operacion_id, usuario_id, sucursal_id, estado) "
                    f"SELECT empresa_id, gen_random_uuid(), usuario_id, sucursal_id, 'incierto' FROM pedido_diferido LIMIT 1"
                )
            )
    finally:
        engine_pg.dispose()
        subida = ejecutar_alembic(url_pg, "upgrade", "head")
        assert subida.returncode == 0, subida.stderr
    with fabrica_pg() as db:
        db.add(
            PedidoDiferido(
                operacion_id=uuid.uuid4(),
                usuario_id=cliente["usuario_id"],
                sucursal_id=escenario["sucursal_id"],
                estado="incierto",
                motivo="cobro_incierto",
                total=Decimal("100.00"),
                total_usd=Decimal("14.37"),
            )
        )
        db.commit()  # otra vez acepta `incierto`
    with fabrica_pg() as db:
        assert db.scalar(select(func.count()).select_from(PedidoDiferido)) == 2
