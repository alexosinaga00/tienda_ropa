"""CU-38 — Generar reporte por comando de voz: la respuesta en lenguaje natural
sale de las cifras reales del reporte. Groq se reemplaza por un intérprete
falso (sin red ni API key); lo que se prueba es qué se hace con lo que
interpretó."""

import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.core.rate_limit import limiter
from app.inteligencia.politicas import redactar_respuesta_reporte
from app.inteligencia.schemas import FiltrosReporteVoz
from app.reportes.schemas import (
    DashboardRespuesta,
    FilaReservasPorEstado,
    FilaTopProducto,
    ReporteInventarioRespuesta,
    ReporteReservasRespuesta,
    ReporteVentasRespuesta,
    ResumenVentas,
)
from app.reportes.politicas import ticket_promedio
from app.ventas.repository import VW_VENTAS_DETALLE_SQL
from tests.conftest import crear_staff
from tests.ventas.test_ventas import _pagar_en_caja, _payload_presencial, contexto  # noqa: F401

RUTA = "/api/v1/ia/reporte-voz"
MODULO_CU = "app.inteligencia.casos_uso.cu38_generar_reporte_comando_voz"
HOY = dt.date(2026, 9, 20)


# ---- Fixtures ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _limpiar_limite():
    # 15/min por IP y todas las pruebas comparten la IP del cliente de pruebas.
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture()
def vista_ventas(db_session):
    # conftest solo crea la vista de inventario; los reportes de ventas necesitan esta.
    db_session.execute(text(VW_VENTAS_DETALLE_SQL))
    db_session.commit()


@pytest.fixture()
def sumas_decimales(monkeypatch):
    """SQLite (solo las pruebas) devuelve float en SUM(); PostgreSQL devuelve
    Decimal, que es lo que espera ticket_promedio(). Se convierte acá, sin
    tocar el paquete `reportes`, para las pruebas que pasan ventas reales por CU-33."""
    monkeypatch.setattr(
        "app.reportes.casos_uso.cu33_consultar_reportes_ventas_inventario.ticket_promedio",
        lambda total, transacciones: ticket_promedio(Decimal(str(total)), transacciones),
    )


class _InterpreteFalso:
    def __init__(self, filtros: FiltrosReporteVoz | None) -> None:
        self._filtros = filtros

    def parsear(self, texto: str) -> FiltrosReporteVoz | None:
        return self._filtros


@pytest.fixture()
def dictar(monkeypatch):
    """dictar(FiltrosReporteVoz(...)) o dictar(None) = Groq falló / sin API key."""

    def _dictar(filtros: FiltrosReporteVoz | None) -> None:
        monkeypatch.setattr(f"{MODULO_CU}.obtener_parser_reporte_voz", lambda: _InterpreteFalso(filtros))

    return _dictar


def _preguntar(client, headers, texto="como van las ventas"):
    return client.post(RUTA, json={"texto": texto}, headers=headers)


def _vender_una(client, ctx):
    """Una venta presencial pagada: 1 unidad a 100.00 (costo 10.00)."""
    venta = client.post(
        "/api/v1/ventas/presencial", json=_payload_presencial(ctx), headers=ctx["cajero_headers"]
    ).json()
    assert _pagar_en_caja(client, ctx["cajero_headers"], venta["id"]).status_code == 201


def _otra_sucursal(client, admin_headers):
    ciudad = client.post(
        "/api/v1/ciudades", json={"nombre": "Cochabamba Voz", "departamento": "Cochabamba"}, headers=admin_headers
    ).json()
    return client.post(
        "/api/v1/sucursales",
        json={"ciudad_id": ciudad["id"], "codigo": "SUC-VOZ-B", "nombre": "Sucursal Norte", "direccion": "Av. 2"},
        headers=admin_headers,
    ).json()


# ---- Redacción (sin BD) ------------------------------------------------------------------


def _reporte_ventas(transacciones=3, total="1250.5", top=True) -> ReporteVentasRespuesta:
    return ReporteVentasRespuesta(
        resumen=ResumenVentas(
            transacciones=transacciones,
            total_ventas=Decimal(total),
            ticket_promedio=Decimal("416.83"),
            margen_bruto=Decimal("300"),
        ),
        top_productos=[FilaTopProducto(producto_id=1, producto="Camisa Oxford", cantidad_vendida=5, total_vendido=Decimal("600"))]
        if top
        else [],
        por_canal=[],
        por_sucursal=[],
        detalle=[],
    )


def _redactar(tipo, resultado, **extra):
    datos = {"entendida": True, "desde": dt.date(2026, 8, 21), "hasta": HOY, "sucursal": None, "categoria": None, "canal": None}
    datos.update(extra)
    return redactar_respuesta_reporte(tipo_reporte=tipo, resultado=resultado, **datos)


def test_redactar_ventas_con_cifras_y_formato_boliviano():
    texto = _redactar("ventas", _reporte_ventas())
    assert texto == (
        "Entre el 21/08/2026 y el 20/09/2026 hubo 3 ventas por Bs 1.250,50, con un ticket promedio de Bs 416,83 "
        "y un margen bruto de Bs 300,00. Lo más vendido fue Camisa Oxford (5 unidades)."
    )


def test_redactar_ventas_singular_sin_ventas_y_sin_top():
    assert "hubo 1 venta por" in _redactar("ventas", _reporte_ventas(transacciones=1, top=False))
    assert "Lo más vendido" not in _redactar("ventas", _reporte_ventas(transacciones=1, top=False))
    assert _redactar("ventas", _reporte_ventas(transacciones=0)).endswith("no hubo ventas.")


def test_redactar_menciona_solo_los_filtros_que_el_reporte_aplica():
    ventas = _redactar("ventas", _reporte_ventas(), sucursal="Sucursal Centro", categoria="Camisas", canal="digital")
    assert "(en Sucursal Centro, categoría Camisas, canal digital)" in ventas

    # Reservas solo filtra por sucursal: categoría y canal no se mencionan.
    reservas = _redactar(
        "reservas",
        ReporteReservasRespuesta(por_estado=[FilaReservasPorEstado(codigo="pendiente", nombre="Pendiente", cantidad=2)], tasa_conversion=0.5),
        sucursal="Sucursal Centro",
        categoria="Camisas",
        canal="digital",
    )
    assert "(en Sucursal Centro)" in reservas
    assert "Camisas" not in reservas and "digital" not in reservas


def test_redactar_reservas_con_tasa_en_porcentaje_y_sin_reservas():
    con = ReporteReservasRespuesta(
        por_estado=[
            FilaReservasPorEstado(codigo="pendiente", nombre="Pendiente", cantidad=2),
            FilaReservasPorEstado(codigo="cancelada", nombre="Cancelada", cantidad=0),
            FilaReservasPorEstado(codigo="completada", nombre="Completada", cantidad=1),
        ],
        tasa_conversion=0.3333,
    )
    texto = _redactar("reservas", con)
    assert "hubo 3 reservas (2 pendiente, 1 completada)" in texto
    assert "tasa de conversión a venta fue de 33,3%" in texto  # las de cantidad 0 no se listan

    sin = ReporteReservasRespuesta(por_estado=[FilaReservasPorEstado(codigo="pendiente", nombre="Pendiente", cantidad=0)], tasa_conversion=0.0)
    assert _redactar("reservas", sin).endswith("no hubo reservas.")


def test_redactar_un_solo_dia_no_dice_entre_una_fecha_y_la_misma():
    texto = _redactar("ventas", _reporte_ventas(), desde=HOY, hasta=HOY)
    assert texto.startswith("El 20/09/2026 hubo 3 ventas por")
    assert "Entre el" not in texto


def test_redactar_inventario_vacio_y_sin_periodo():
    texto = _redactar("inventario", ReporteInventarioRespuesta(consolidado=[], alertas=[], valuacion=[]))
    assert texto == "Al día de hoy no hay existencias registradas."


def _dashboard() -> DashboardRespuesta:
    return DashboardRespuesta(
        desde=dt.date(2026, 8, 21),
        hasta=HOY,
        ventas_del_periodo=Decimal("980"),
        transacciones=1,
        ticket_promedio=Decimal("980"),
        margen_bruto=Decimal("400"),
        top_productos=[],
        ventas_por_canal=[],
        ventas_por_sucursal=[],
        valor_inventario_total=Decimal("12400"),
        variantes_bajo_minimo=2,
        reservas_por_estado=[],
        tasa_conversion_reservas=0.25,
        uso_probador=[],
    )


def test_redactar_dashboard_y_aviso_cuando_no_se_entendio():
    entendida = _redactar("dashboard", _dashboard())
    assert entendida.startswith("Entre el 21/08/2026 y el 20/09/2026 las ventas sumaron Bs 980,00 en 1 transacción")
    assert "El inventario vale Bs 12.400,00 y hay 2 variantes por debajo del stock mínimo" in entendida
    assert "tasa de conversión de reservas es de 25%" in entendida

    sin_alertas = _dashboard().model_copy(update={"variantes_bajo_minimo": 0})
    assert "y ninguna variante está por debajo del stock mínimo" in _redactar("dashboard", sin_alertas)

    no_entendida = _redactar("dashboard", _dashboard(), entendida=False)
    assert no_entendida.startswith("No identifiqué qué reporte pedías, así que te muestro el resumen general. Entre el")


# ---- Endpoint ----------------------------------------------------------------------------


def test_ventas_responde_con_las_cifras_reales(
    client, admin_headers, contexto, vista_ventas, sumas_decimales, dictar  # noqa: F811
):
    _vender_una(client, contexto)
    dictar(FiltrosReporteVoz(tipo_reporte="ventas"))

    respuesta = _preguntar(client, admin_headers)

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["tipo_reporte"] == "ventas"
    assert "hubo 1 venta por Bs 100,00" in cuerpo["respuesta"]
    assert "margen bruto de Bs 90,00" in cuerpo["respuesta"]
    assert cuerpo["resultado"]["resumen"]["transacciones"] == 1  # los datos siguen viniendo
    assert set(cuerpo["filtros_aplicados"]) == {"desde", "hasta", "sucursal_id", "categoria_id", "canal"}


@pytest.mark.parametrize("tipo", ["inventario", "reservas", "dashboard"])
def test_cada_tipo_de_reporte_responde_en_espanol(client, admin_headers, contexto, vista_ventas, dictar, tipo):  # noqa: F811
    dictar(FiltrosReporteVoz(tipo_reporte=tipo))

    respuesta = _preguntar(client, admin_headers)

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["tipo_reporte"] == tipo
    assert cuerpo["respuesta"].strip() != ""
    assert not cuerpo["respuesta"].startswith("No identifiqué")


@pytest.mark.parametrize("interpretacion", [None, FiltrosReporteVoz(tipo_reporte="inventado")])
def test_sin_interpretacion_valida_muestra_el_dashboard_y_lo_avisa(
    client, admin_headers, vista_ventas, dictar, interpretacion
):
    dictar(interpretacion)

    respuesta = _preguntar(client, admin_headers)

    assert respuesta.status_code == 200  # nunca un error por lo que interpretó Groq
    cuerpo = respuesta.json()
    assert cuerpo["tipo_reporte"] == "dashboard"
    assert cuerpo["respuesta"].startswith("No identifiqué qué reporte pedías")


def test_rango_invertido_se_corrige_en_vez_de_fallar(client, admin_headers, vista_ventas, dictar):
    dictar(FiltrosReporteVoz(tipo_reporte="ventas", desde=dt.date(2026, 9, 20), hasta=dt.date(2026, 8, 1)))

    respuesta = _preguntar(client, admin_headers)

    assert respuesta.status_code == 200
    assert respuesta.json()["filtros_aplicados"]["desde"] == "2026-08-01"
    assert respuesta.json()["respuesta"].startswith("Entre el 01/08/2026 y el 20/09/2026")


def test_filtros_dictados_se_resuelven_y_se_nombran(
    client, admin_headers, contexto, vista_ventas, sumas_decimales, dictar  # noqa: F811
):
    _vender_una(client, contexto)
    dictar(FiltrosReporteVoz(tipo_reporte="ventas", sucursal="Sucursal Venta", canal="presencial"))

    cuerpo = _preguntar(client, admin_headers).json()

    assert cuerpo["filtros_aplicados"]["sucursal_id"] == contexto["sucursal_id"]
    assert cuerpo["filtros_aplicados"]["canal"] == "presencial"
    assert "(en Sucursal Venta, canal presencial)" in cuerpo["respuesta"]
    assert "hubo 1 venta" in cuerpo["respuesta"]


def test_el_encargado_solo_recibe_su_sucursal_aunque_dicte_otra(
    client, db_session, admin_headers, contexto, vista_ventas, sumas_decimales, dictar  # noqa: F811
):
    otra = _otra_sucursal(client, admin_headers)
    encargado = crear_staff(
        client, admin_headers, db_session, rol="encargado_sucursal", cargo="Encargado",
        sucursal_id=contexto["sucursal_id"], email="encargado.voz@example.com",
    )
    _vender_una(client, contexto)
    dictar(FiltrosReporteVoz(tipo_reporte="ventas", sucursal=otra["nombre"]))

    cuerpo = _preguntar(client, encargado).json()

    assert cuerpo["filtros_aplicados"]["sucursal_id"] == contexto["sucursal_id"]
    assert "hubo 1 venta" in cuerpo["respuesta"]  # ve las de su sucursal, no un reporte vacío ni un 403


def test_sin_el_permiso_de_reportes_no_se_puede_preguntar(client, cliente_headers, dictar):
    dictar(FiltrosReporteVoz(tipo_reporte="ventas"))
    assert _preguntar(client, cliente_headers).status_code == 403
    assert client.post(RUTA, json={"texto": "ventas"}).status_code == 401


def test_texto_vacio_o_demasiado_largo_se_rechaza(client, admin_headers):
    assert _preguntar(client, admin_headers, texto="").status_code == 422
    assert _preguntar(client, admin_headers, texto="x" * 301).status_code == 422
