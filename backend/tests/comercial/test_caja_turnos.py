"""Caja por turno (E21): abrir, vender, cerrar contando el efectivo, y la supervisión.

La caja es de la SUCURSAL (un solo turno abierto a la vez). El esperado es `monto inicial + efectivo cobrado en la sucursal
durante el turno - efectivo reembolsado durante el turno`; el efectivo se filtra por el MÉTODO de pago y no depende de qué
cajero registró cada venta. Cierre ciego: el cajero no ve el esperado hasta que cierra. Un turno no pasa del día (hora de
Bolivia): al terminar se cierra solo, sin conteo, y un supervisor puede completar el conteo. Las pruebas usan el reloj real
y mueven con la base las fechas de apertura y de los pagos (SQLite trunca `now()` a segundos)."""

import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.comercial.models import CajaTurno, Pago
from app.comercial.politicas import cerrar_turnos_vencidos, fin_de_dia_bolivia
from app.core.tiempo import dia_bolivia
from tests.ayudas_bitacora import filas_de
from tests.comercial.test_cambio_talla import VENDIDAS, _devolver, ctx  # noqa: F401  (el contexto de una sucursal con stock)
from tests.conftest import crear_cajero, crear_staff

API = "/api/v1"


@pytest.fixture()
def reloj():
    """Sin reloj falso: el contexto compartido (`ctx`) lo pide, pero aquí las fechas se mueven en la base."""
    return None


def _ahora() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


def _abrir(client, headers, monto="100.00", **extra):
    return client.post(f"{API}/caja/turnos", json={"monto_inicial": monto, **extra}, headers=headers)


def _turno_abierto(client, db_session, headers, monto="100.00") -> dict:
    """Abre el turno y adelanta su apertura 30 segundos al pasado: así los pagos que se hacen enseguida (con `now()` de
    SQLite, truncado a segundos) caen dentro de la ventana."""
    respuesta = _abrir(client, headers, monto)
    assert respuesta.status_code == 201, respuesta.text
    turno = db_session.get(CajaTurno, respuesta.json()["id"])
    turno.apertura_en = turno.apertura_en - dt.timedelta(seconds=30)
    db_session.commit()
    return respuesta.json()


def _vender(client, ctx, metodo="efectivo", *, unidades=1, variante=None, headers=None, sucursal_id=None) -> tuple[dict, int]:
    headers = headers or ctx["cajero_headers"]
    cuerpo = {
        "sucursal_id": sucursal_id or ctx["sucursal_id"],
        "detalle": [{"variante_id": variante or ctx["m"], "cantidad": unidades}],
    }
    venta = client.post(f"{API}/ventas/presencial", json=cuerpo, headers=headers)
    assert venta.status_code == 201, venta.text
    pago = {"venta_id": venta.json()["id"], "metodo_pago": metodo}
    if metodo == "efectivo":
        pago["monto_recibido"] = "99999"
    cobro = client.post(f"{API}/pagos/caja", json=pago, headers=headers)
    assert cobro.status_code == 201, cobro.text
    return venta.json(), cobro.json()["pago"]["id"]


def _cerrar(client, headers, turno_id, contado, observacion=None, **extra):
    cuerpo = {"efectivo_contado": contado, **extra}
    if observacion is not None:
        cuerpo["observacion"] = observacion
    return client.post(f"{API}/caja/turnos/{turno_id}/cerrar", json=cuerpo, headers=headers)


def _otra_sucursal(client, admin_headers) -> int:
    ciudad = client.post(f"{API}/ciudades", json={"nombre": "Ciudad Dos", "departamento": "Dos"}, headers=admin_headers)
    respuesta = client.post(
        f"{API}/sucursales",
        json={"ciudad_id": ciudad.json()["id"], "codigo": "SUC-DOS", "nombre": "Sucursal Dos", "direccion": "Av. 2"},
        headers=admin_headers,
    )
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()["id"]


def _fechar_pago(db_session, pago_id: int, fecha: dt.datetime) -> None:
    db_session.get(Pago, pago_id).fecha = fecha
    db_session.commit()


# ---- abrir ---------------------------------------------------------------------------------------------------------


def test_abrir_el_turno_deja_la_caja_de_la_sucursal_abierta_sin_mostrar_el_esperado(client, ctx):
    respuesta = _abrir(client, ctx["cajero_headers"], "100.00", observacion="Apertura")

    assert respuesta.status_code == 201, respuesta.text
    turno = respuesta.json()
    assert turno["estado"] == "abierta" and turno["sucursal_id"] == ctx["sucursal_id"]
    assert turno["monto_inicial"] == "100.00" and turno["abierto_por_nombre"] == "Staff Prueba"
    assert turno["apertura_en"].endswith("Z") and turno["cierre_en"] is None
    # Cierre ciego: el cajero no ve cuánto debería haber en el cajón.
    assert turno["monto_esperado"] is None and turno["resumen"] is None


def test_no_se_abren_dos_turnos_en_la_misma_sucursal_ni_por_otro_cajero(client, db_session, admin_headers, ctx):
    assert _abrir(client, ctx["cajero_headers"]).status_code == 201
    otro = crear_cajero(client, admin_headers, db_session, sucursal_id=ctx["sucursal_id"], email="cajero2@example.com")

    for headers in (ctx["cajero_headers"], otro):
        respuesta = _abrir(client, headers)
        assert respuesta.status_code == 409
        assert respuesta.json()["codigo"] == "turno_ya_abierto"


def test_abrir_valida_el_monto_y_la_sucursal(client, admin_headers, ctx):
    assert _abrir(client, ctx["cajero_headers"], "-1").status_code == 422
    # Quien opera todas las sucursales (el administrador) tiene que indicar cuál.
    sin_sucursal = _abrir(client, admin_headers)
    assert sin_sucursal.status_code == 400
    con_sucursal = _abrir(client, admin_headers, sucursal_id=ctx["sucursal_id"])
    assert con_sucursal.status_code == 201 and con_sucursal.json()["sucursal_id"] == ctx["sucursal_id"]
    # El cajero no abre la caja de otra sucursal.
    otra = _otra_sucursal(client, admin_headers)
    assert _abrir(client, ctx["cajero_headers"], sucursal_id=otra).status_code == 403


def test_el_turno_actual_y_el_monto_inicial_sugerido(client, db_session, ctx):
    vacio = client.get(f"{API}/caja/turnos/actual", headers=ctx["cajero_headers"])
    assert vacio.status_code == 200 and vacio.json()["turno"] is None and vacio.json()["monto_inicial_sugerido"] is None

    turno = _turno_abierto(client, db_session, ctx["cajero_headers"])
    actual = client.get(f"{API}/caja/turnos/actual", headers=ctx["cajero_headers"])
    assert actual.json()["turno"]["id"] == turno["id"] and actual.json()["turno"]["monto_esperado"] is None

    assert _cerrar(client, ctx["cajero_headers"], turno["id"], "100.00").status_code == 200
    siguiente = client.get(f"{API}/caja/turnos/actual", headers=ctx["cajero_headers"]).json()
    assert siguiente["turno"] is None and siguiente["monto_inicial_sugerido"] == "100.00"  # lo que se contó al cerrar


# ---- cerrar: el esperado -----------------------------------------------------------------------------------------------


def test_cerrar_sin_ventas_cuadra_y_no_pide_observacion(client, db_session, ctx):
    turno = _turno_abierto(client, db_session, ctx["cajero_headers"], "100.00")

    cierre = _cerrar(client, ctx["cajero_headers"], turno["id"], "100.00")

    assert cierre.status_code == 200, cierre.text
    datos = cierre.json()
    assert datos["estado"] == "cerrada" and datos["cierre_automatico"] is False
    assert datos["monto_esperado"] == "100.00" and datos["efectivo_contado"] == "100.00" and datos["diferencia"] == "0.00"
    assert datos["cerrado_por_id"] == datos["abierto_por_id"]


def test_el_esperado_suma_el_efectivo_y_deja_afuera_el_qr(client, db_session, ctx):
    turno = _turno_abierto(client, db_session, ctx["cajero_headers"], "100.00")
    _vender(client, ctx, "efectivo", unidades=1)  # Bs 100
    _vender(client, ctx, "efectivo", unidades=2)  # Bs 200
    _vender(client, ctx, "qr", unidades=1)  # Bs 100: no pasa por el cajón

    cierre = _cerrar(client, ctx["cajero_headers"], turno["id"], "400.00")

    assert cierre.status_code == 200, cierre.text
    resumen = cierre.json()["resumen"]
    assert resumen["ventas_efectivo"] == "300.00" and resumen["cantidad_ventas"] == 2
    assert resumen["ventas_otros_metodos"] == "100.00" and resumen["reembolsos_efectivo"] == "0.00"
    assert cierre.json()["monto_esperado"] == "400.00" and cierre.json()["diferencia"] == "0.00"


def test_una_devolucion_en_efectivo_resta_pero_una_en_qr_no(client, db_session, ctx):
    turno = _turno_abierto(client, db_session, ctx["cajero_headers"], "100.00")
    venta_efectivo, _ = _vender(client, ctx, "efectivo", unidades=VENDIDAS)  # Bs 400
    venta_qr, _ = _vender(client, ctx, "qr", unidades=VENDIDAS)  # Bs 400
    assert _devolver(client, ctx, venta_efectivo, cantidad=1).status_code == 201  # sale Bs 100 del cajón
    assert _devolver(client, ctx, venta_qr, cantidad=1).status_code == 201  # el QR no pasó por el cajón

    cierre = _cerrar(client, ctx["cajero_headers"], turno["id"], "400.00")

    assert cierre.status_code == 200, cierre.text
    resumen = cierre.json()["resumen"]
    assert resumen["reembolsos_efectivo"] == "100.00"
    assert cierre.json()["monto_esperado"] == "400.00"  # 100 inicial + 400 cobrado - 100 devuelto


def test_un_cambio_de_talla_no_mueve_el_cajon(client, db_session, ctx):
    turno = _turno_abierto(client, db_session, ctx["cajero_headers"], "100.00")
    venta, _ = _vender(client, ctx, "efectivo", unidades=VENDIDAS)
    assert _devolver(client, ctx, venta, cantidad=1, nueva=ctx["l"]).status_code == 201

    cierre = _cerrar(client, ctx["cajero_headers"], turno["id"], "500.00")

    assert cierre.json()["resumen"]["reembolsos_efectivo"] == "0.00" and cierre.json()["monto_esperado"] == "500.00"


def test_anular_un_pago_en_efectivo_resta_en_el_turno_donde_ocurre(client, db_session, admin_headers, ctx):
    turno = _turno_abierto(client, db_session, ctx["cajero_headers"], "100.00")
    _venta, pago_id = _vender(client, ctx, "efectivo", unidades=2)  # Bs 200
    assert client.post(f"{API}/pagos/{pago_id}/anular", headers=admin_headers).status_code == 200

    cierre = _cerrar(client, ctx["cajero_headers"], turno["id"], "100.00")

    assert cierre.json()["resumen"]["ventas_efectivo"] == "200.00" and cierre.json()["resumen"]["reembolsos_efectivo"] == "200.00"
    assert cierre.json()["monto_esperado"] == "100.00" and cierre.json()["diferencia"] == "0.00"


def test_otro_cajero_de_la_misma_sucursal_suma_al_mismo_cajon(client, db_session, admin_headers, ctx):
    turno = _turno_abierto(client, db_session, ctx["cajero_headers"], "100.00")
    otro = crear_cajero(client, admin_headers, db_session, sucursal_id=ctx["sucursal_id"], email="cajero2@example.com")
    _vender(client, ctx, "efectivo", unidades=1, headers=otro)  # lo registra el otro cajero

    cierre = _cerrar(client, ctx["cajero_headers"], turno["id"], "200.00")

    assert cierre.json()["monto_esperado"] == "200.00" and cierre.json()["resumen"]["cantidad_ventas"] == 1


def test_no_cuentan_ventas_pendientes_otra_sucursal_ni_pagos_anteriores_a_la_apertura(client, db_session, admin_headers, ctx):
    turno = _turno_abierto(client, db_session, ctx["cajero_headers"], "100.00")
    # Una venta que nunca se cobró.
    pendiente = client.post(
        f"{API}/ventas/presencial",
        json={"sucursal_id": ctx["sucursal_id"], "detalle": [{"variante_id": ctx["m"], "cantidad": 1}]},
        headers=ctx["cajero_headers"],
    )
    assert pendiente.status_code == 201
    # Una venta cobrada ANTES de abrir el turno.
    _antes, pago_antes = _vender(client, ctx, "efectivo", unidades=1)
    _fechar_pago(db_session, pago_antes, _ahora() - dt.timedelta(hours=1))
    # Una venta de otra sucursal.
    otra = _otra_sucursal(client, admin_headers)
    client.post(
        f"{API}/inventario/movimientos",
        json={"variante_id": ctx["m"], "sucursal_id": otra, "tipo_movimiento_codigo": "recepcion", "cantidad": 5, "costo_unitario": "10.00"},
        headers=admin_headers,
    )
    cajero_otra = crear_cajero(client, admin_headers, db_session, sucursal_id=otra, email="cajero3@example.com")
    _vender(client, ctx, "efectivo", unidades=1, headers=cajero_otra, sucursal_id=otra)

    cierre = _cerrar(client, ctx["cajero_headers"], turno["id"], "100.00")

    assert cierre.json()["monto_esperado"] == "100.00" and cierre.json()["resumen"]["cantidad_ventas"] == 0


# ---- cerrar: la diferencia y los permisos --------------------------------------------------------------------------------


@pytest.mark.parametrize("contado, diferencia", [("95.00", "-5.00"), ("107.50", "7.50")])
def test_una_diferencia_exige_observacion_y_queda_guardada(client, db_session, ctx, contado, diferencia):
    turno = _turno_abierto(client, db_session, ctx["cajero_headers"], "100.00")

    sin_observacion = _cerrar(client, ctx["cajero_headers"], turno["id"], contado)
    assert sin_observacion.status_code == 400 and sin_observacion.json()["codigo"] == "observacion_requerida"
    # El rechazo no cierra nada ni revela el esperado.
    assert db_session.get(CajaTurno, turno["id"]).estado == "abierta"
    assert "100.00" not in sin_observacion.text

    con_observacion = _cerrar(client, ctx["cajero_headers"], turno["id"], contado, observacion="Faltó dar vuelto")
    assert con_observacion.status_code == 200, con_observacion.text
    assert con_observacion.json()["diferencia"] == diferencia and con_observacion.json()["observacion_cierre"] == "Faltó dar vuelto"


def test_el_cierre_no_se_repite_ni_lo_hace_otro_cajero_pero_si_un_supervisor(client, db_session, admin_headers, ctx):
    turno = _turno_abierto(client, db_session, ctx["cajero_headers"], "100.00")
    otro = crear_cajero(client, admin_headers, db_session, sucursal_id=ctx["sucursal_id"], email="cajero2@example.com")

    ajeno = _cerrar(client, otro, turno["id"], "100.00")
    assert ajeno.status_code == 403 and ajeno.json()["codigo"] == "turno_de_otro_cajero"

    por_supervisor = _cerrar(client, admin_headers, turno["id"], "100.00")
    assert por_supervisor.status_code == 200 and por_supervisor.json()["cerrado_por_nombre"] == "Admin Root"
    assert db_session.get(CajaTurno, turno["id"]).abierto_por_id != db_session.get(CajaTurno, turno["id"]).cerrado_por_id

    de_nuevo = _cerrar(client, ctx["cajero_headers"], turno["id"], "100.00")
    assert de_nuevo.status_code == 409 and de_nuevo.json()["codigo"] == "turno_cerrado"


def test_el_cajero_no_ve_los_cierres_pero_el_encargado_solo_los_de_su_sucursal(client, db_session, admin_headers, ctx):
    turno = _turno_abierto(client, db_session, ctx["cajero_headers"], "100.00")
    assert _cerrar(client, ctx["cajero_headers"], turno["id"], "100.00").status_code == 200
    otra = _otra_sucursal(client, admin_headers)
    cajero_otra = crear_cajero(client, admin_headers, db_session, sucursal_id=otra, email="cajero3@example.com")
    turno_otra = _abrir(client, cajero_otra, "50.00")
    assert turno_otra.status_code == 201
    encargado = crear_staff(
        client, admin_headers, db_session, rol="encargado_sucursal", cargo="Encargado", sucursal_id=ctx["sucursal_id"], email="enc@example.com"
    )

    assert client.get(f"{API}/caja/turnos", headers=ctx["cajero_headers"]).status_code == 403
    assert client.get(f"{API}/caja/turnos/estado", headers=ctx["cajero_headers"]).status_code == 403
    del_encargado = client.get(f"{API}/caja/turnos", headers=encargado)
    assert del_encargado.status_code == 200
    assert {t["sucursal_id"] for t in del_encargado.json()} == {ctx["sucursal_id"]}
    # Un turno de otra sucursal está fuera de su alcance.
    assert client.get(f"{API}/caja/turnos/{turno_otra.json()['id']}", headers=encargado).status_code == 403
    del_administrador = client.get(f"{API}/caja/turnos", headers=admin_headers)
    assert {t["sucursal_id"] for t in del_administrador.json()} == {ctx["sucursal_id"], otra}
    # El supervisor ve el esperado de un turno que sigue abierto.
    vivo = client.get(f"{API}/caja/turnos?estado=abierta", headers=admin_headers).json()
    assert vivo[0]["monto_esperado"] == "50.00"


def test_las_cajas_de_hoy_muestran_el_turno_abierto_de_cada_sucursal(client, db_session, admin_headers, ctx):
    _turno_abierto(client, db_session, ctx["cajero_headers"], "100.00")
    _vender(client, ctx, "efectivo", unidades=1)
    otra = _otra_sucursal(client, admin_headers)

    cajas = client.get(f"{API}/caja/turnos/estado", headers=admin_headers)

    assert cajas.status_code == 200, cajas.text
    por_sucursal = {c["sucursal_id"]: c for c in cajas.json()}
    assert por_sucursal[ctx["sucursal_id"]]["turno"]["monto_esperado"] == "200.00"
    assert por_sucursal[otra]["turno"] is None


# ---- cierre automático al terminar el día -------------------------------------------------------------------------------


def _mediodia_boliviano(dias_atras: int) -> dt.datetime:
    """El mediodía de Bolivia (16:00 UTC) de hace `dias_atras` DÍAS DE BOLIVIA: lejos de cualquier frontera de día. Se
    cuenta con la fecha de Bolivia (no la de UTC), que puede ir un día atrás durante las primeras 4 horas del día UTC."""
    hoy_en_bolivia = dia_bolivia()[0]
    return dt.datetime.combine(hoy_en_bolivia - dt.timedelta(days=dias_atras), dt.time(16, 0))


def _turno_de_otro_dia(client, db_session, ctx, dias_atras: int, monto="100.00") -> dict:
    turno = _turno_abierto(client, db_session, ctx["cajero_headers"], monto)
    fila = db_session.get(CajaTurno, turno["id"])
    fila.apertura_en = _mediodia_boliviano(dias_atras)
    db_session.commit()
    return turno


def test_un_turno_olvidado_se_cierra_solo_sin_conteo_y_no_bloquea_el_siguiente(client, db_session, ctx):
    viejo = _turno_de_otro_dia(client, db_session, ctx, 1)
    venta, pago_id = _vender(client, ctx, "efectivo", unidades=1)
    _fechar_pago(db_session, pago_id, _mediodia_boliviano(1) + dt.timedelta(hours=1))  # se cobró dentro de ese turno

    nuevo = _abrir(client, ctx["cajero_headers"], "50.00")  # abrir cierra primero el turno vencido

    assert nuevo.status_code == 201, nuevo.text
    db_session.expire_all()
    cerrado = db_session.get(CajaTurno, viejo["id"])
    assert cerrado.estado == "cerrada_auto" and cerrado.cerrado_por_id is None
    assert cerrado.cierre_en == fin_de_dia_bolivia(_mediodia_boliviano(1))
    assert cerrado.efectivo_contado is None and cerrado.diferencia is None
    assert cerrado.monto_esperado == Decimal("200.00")  # 100 inicial + la venta de Bs 100 de ese turno
    assert filas_de(db_session, "cierre_caja", "cierre_automatico")[0].datos["monto_esperado"] == "200.00"


def test_la_tarea_periodica_cierra_los_turnos_vencidos(client, db_session, ctx):
    _turno_de_otro_dia(client, db_session, ctx, 2)

    assert cerrar_turnos_vencidos(db_session) == 1
    assert cerrar_turnos_vencidos(db_session) == 0  # idempotente

    abiertos = db_session.scalars(select(CajaTurno).where(CajaTurno.estado == "abierta")).all()
    assert abiertos == []


def test_el_supervisor_completa_el_conteo_una_sola_vez_y_dentro_del_plazo(client, db_session, admin_headers, ctx):
    viejo = _turno_de_otro_dia(client, db_session, ctx, 1)
    cerrar_turnos_vencidos(db_session)

    detalle = client.get(f"{API}/caja/turnos/{viejo['id']}", headers=admin_headers).json()
    assert detalle["estado"] == "cerrada_auto" and detalle["cierre_automatico"] is True
    assert detalle["efectivo_contado"] is None and detalle["conteo_hasta"].endswith("Z")

    sin_observacion = client.post(
        f"{API}/caja/turnos/{viejo['id']}/completar-conteo", json={"efectivo_contado": "95.00", "observacion": ""}, headers=admin_headers
    )
    assert sin_observacion.status_code == 422
    cajero = client.post(
        f"{API}/caja/turnos/{viejo['id']}/completar-conteo",
        json={"efectivo_contado": "95.00", "observacion": "Conté yo"},
        headers=ctx["cajero_headers"],
    )
    assert cajero.status_code == 403

    completado = client.post(
        f"{API}/caja/turnos/{viejo['id']}/completar-conteo",
        json={"efectivo_contado": "95.00", "observacion": "Faltaron Bs 5"},
        headers=admin_headers,
    )
    assert completado.status_code == 200, completado.text
    assert completado.json()["efectivo_contado"] == "95.00" and completado.json()["diferencia"] == "-5.00"
    assert completado.json()["conteo_por_nombre"] == "Admin Root" and completado.json()["conteo_hasta"] is None
    de_nuevo = client.post(
        f"{API}/caja/turnos/{viejo['id']}/completar-conteo",
        json={"efectivo_contado": "95.00", "observacion": "Otra vez"},
        headers=admin_headers,
    )
    assert de_nuevo.status_code == 409 and de_nuevo.json()["codigo"] == "conteo_ya_registrado"


def test_pasadas_72_horas_ya_no_se_completa_el_conteo(client, db_session, admin_headers, ctx):
    viejo = _turno_de_otro_dia(client, db_session, ctx, 6)
    cerrar_turnos_vencidos(db_session)

    respuesta = client.post(
        f"{API}/caja/turnos/{viejo['id']}/completar-conteo",
        json={"efectivo_contado": "100.00", "observacion": "Tarde"},
        headers=admin_headers,
    )

    assert respuesta.status_code == 409 and respuesta.json()["codigo"] == "conteo_fuera_de_plazo"


def test_solo_se_completa_el_conteo_de_un_turno_cerrado_automaticamente(client, db_session, admin_headers, ctx):
    turno = _turno_abierto(client, db_session, ctx["cajero_headers"], "100.00")
    assert _cerrar(client, ctx["cajero_headers"], turno["id"], "100.00").status_code == 200

    respuesta = client.post(
        f"{API}/caja/turnos/{turno['id']}/completar-conteo",
        json={"efectivo_contado": "100.00", "observacion": "Ya estaba contado"},
        headers=admin_headers,
    )

    assert respuesta.status_code == 409 and respuesta.json()["codigo"] == "conteo_no_aplica"


def test_el_cierre_ya_hecho_no_cambia_y_el_detalle_muestra_el_ajuste_posterior(client, db_session, admin_headers, ctx):
    turno = _turno_abierto(client, db_session, ctx["cajero_headers"], "100.00")
    cierre = _cerrar(client, ctx["cajero_headers"], turno["id"], "100.00")
    assert cierre.json()["monto_esperado"] == "100.00"
    # Después del cierre llega una venta (de un dispositivo sin conexión) que se cobró dentro del turno.
    _venta, pago_id = _vender(client, ctx, "efectivo", unidades=1)
    fila = db_session.get(CajaTurno, turno["id"])
    _fechar_pago(db_session, pago_id, fila.apertura_en + dt.timedelta(seconds=10))

    detalle = client.get(f"{API}/caja/turnos/{turno['id']}", headers=admin_headers).json()

    assert detalle["monto_esperado"] == "100.00"  # la foto del cierre no cambia
    assert detalle["ajuste_posterior"] == "100.00"  # pero aparece el efectivo que llegó tarde


# ---- bitácora ---------------------------------------------------------------------------------------------------------------


def test_abrir_y_cerrar_dejan_su_fila_de_bitacora_sin_datos_personales(client, db_session, ctx):
    turno = _turno_abierto(client, db_session, ctx["cajero_headers"], "100.00")
    _cerrar(client, ctx["cajero_headers"], turno["id"], "90.00", observacion="Faltó")

    (abrir,) = filas_de(db_session, "cierre_caja", "abrir")
    (cerrar,) = filas_de(db_session, "cierre_caja", "cerrar")
    assert abrir.datos == {"sucursal_id": ctx["sucursal_id"], "monto_inicial": "100.00"}
    assert cerrar.datos["diferencia"] == "-10.00" and cerrar.datos["por_supervisor"] is False
    assert "Faltó" not in str(cerrar.datos)  # el texto libre no se copia a la bitácora
