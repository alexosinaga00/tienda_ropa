import datetime as dt

import pytest

from app.reservas.models import Reserva


def _proxima_fecha_con_dia_semana(dia_semana: int) -> dt.date:
    """Primera fecha, a partir de una semana desde hoy, que cae en el
    `dia_semana` (isoweekday: 1=lunes ... 7=domingo) pedido."""
    base = dt.date.today() + dt.timedelta(days=7)
    delta = (dia_semana - base.isoweekday()) % 7
    return base + dt.timedelta(days=delta)


@pytest.fixture()
def contexto(client, admin_headers):
    cat = client.post("/api/v1/categorias", json={"nombre": "Camisas Reserva"}, headers=admin_headers).json()
    talla = client.post("/api/v1/tallas", json={"codigo": "M", "orden": 1}, headers=admin_headers).json()
    color = client.post("/api/v1/colores", json={"nombre": "Azul Reserva"}, headers=admin_headers).json()
    producto = client.post(
        "/api/v1/productos",
        json={
            "codigo": "RES-1",
            "nombre": "Camisa reserva",
            "categoria_id": cat["id"],
            "precio_base": "100.00",
            "tallas_ids": [talla["id"]],
            "colores_ids": [color["id"]],
        },
        headers=admin_headers,
    ).json()
    variantes = client.get(f"/api/v1/productos/{producto['id']}/variantes", headers=admin_headers).json()
    variante_id = variantes[0]["id"]

    ciudad = client.post(
        "/api/v1/ciudades", json={"nombre": "Santa Cruz Reserva", "departamento": "Santa Cruz"}, headers=admin_headers
    ).json()
    sucursal = client.post(
        "/api/v1/sucursales",
        json={"ciudad_id": ciudad["id"], "codigo": "SUC-RES", "nombre": "Sucursal Reserva", "direccion": "Av. 1"},
        headers=admin_headers,
    ).json()
    sucursal_id = sucursal["id"]

    fecha_visita = _proxima_fecha_con_dia_semana(3)  # miércoles
    client.post(
        f"/api/v1/sucursales/{sucursal_id}/horarios",
        json={"dia_semana": 3, "hora_apertura": "08:00:00", "hora_cierre": "20:00:00"},
        headers=admin_headers,
    )

    # Stock inicial: 5 unidades a costo 10.
    client.post(
        "/api/v1/inventario/movimientos",
        json={
            "variante_id": variante_id,
            "sucursal_id": sucursal_id,
            "tipo_movimiento_codigo": "recepcion",
            "cantidad": 5,
            "costo_unitario": "10.00",
        },
        headers=admin_headers,
    )

    return {
        "producto_id": producto["id"],
        "variante_id": variante_id,
        "color_id": color["id"],
        "sucursal_id": sucursal_id,
        "fecha_visita": fecha_visita.isoformat(),
    }


def _payload_reserva(ctx, cantidad=1, hora_desde="10:00:00", hora_hasta="11:00:00"):
    return {
        "sucursal_id": ctx["sucursal_id"],
        "fecha_visita": ctx["fecha_visita"],
        "hora_visita_desde": hora_desde,
        "hora_visita_hasta": hora_hasta,
        "detalle": [{"variante_id": ctx["variante_id"], "cantidad": cantidad}],
    }


def _disponible(client, headers, ctx):
    stock = client.get(
        f"/api/v1/inventario/stock/{ctx['variante_id']}/{ctx['sucursal_id']}", headers=headers
    ).json()
    return stock["cantidad_disponible"]


# ---- Crear reserva --------------------------------------------------------------


def test_crear_reserva_descuenta_disponible(client, admin_headers, cliente_headers, contexto):
    antes = _disponible(client, admin_headers, contexto)

    respuesta = client.post("/api/v1/reservas", json=_payload_reserva(contexto, cantidad=2), headers=cliente_headers)
    assert respuesta.status_code == 201
    cuerpo = respuesta.json()
    assert cuerpo["estado"] == "pendiente"
    assert len(cuerpo["detalle"]) == 1
    assert cuerpo["detalle"][0]["seleccionada"] is None

    despues = _disponible(client, admin_headers, contexto)
    assert despues == antes - 2


def test_crear_reserva_sin_stock_suficiente_falla(client, admin_headers, cliente_headers, contexto):
    respuesta = client.post(
        "/api/v1/reservas", json=_payload_reserva(contexto, cantidad=999), headers=cliente_headers
    )
    assert respuesta.status_code == 409


def test_crear_reserva_franja_fuera_de_horario_falla(client, cliente_headers, contexto):
    respuesta = client.post(
        "/api/v1/reservas",
        json=_payload_reserva(contexto, hora_desde="06:00:00", hora_hasta="07:00:00"),
        headers=cliente_headers,
    )
    assert respuesta.status_code == 400


def test_crear_reserva_rango_horario_invertido_falla(client, cliente_headers, contexto):
    respuesta = client.post(
        "/api/v1/reservas",
        json=_payload_reserva(contexto, hora_desde="18:00:00", hora_hasta="09:00:00"),
        headers=cliente_headers,
    )
    assert respuesta.status_code == 400


def test_crear_reserva_dia_sin_horario_configurado_falla(client, cliente_headers, contexto):
    payload = _payload_reserva(contexto)
    # Un día distinto al miércoles configurado en el fixture.
    otra_fecha = _proxima_fecha_con_dia_semana(3) + dt.timedelta(days=1)
    payload["fecha_visita"] = otra_fecha.isoformat()
    respuesta = client.post("/api/v1/reservas", json=payload, headers=cliente_headers)
    assert respuesta.status_code == 400


def test_crear_reserva_requiere_autenticacion(client, contexto):
    respuesta = client.post("/api/v1/reservas", json=_payload_reserva(contexto))
    assert respuesta.status_code == 401


def test_crear_reserva_genera_notificaciones_a_empleados(client, admin_headers, cliente_headers, contexto):
    empleado = client.post(
        "/api/v1/usuarios",
        json={
            "nombre": "Enc",
            "apellido": "Argado",
            "email": "encargado_notif@example.com",
            "password": "claveSegura123",
        },
        headers=admin_headers,
    ).json()
    client.post(
        "/api/v1/empleados",
        json={"usuario_id": empleado["id"], "sucursal_id": contexto["sucursal_id"], "cargo": "Encargado"},
        headers=admin_headers,
    )

    respuesta = client.post("/api/v1/reservas", json=_payload_reserva(contexto), headers=cliente_headers)
    assert respuesta.status_code == 201

    token_empleado = client.post(
        "/api/v1/auth/login", json={"email": "encargado_notif@example.com", "password": "claveSegura123"}
    ).json()["access_token"]
    notificaciones = client.get(
        "/api/v1/notificaciones", headers={"Authorization": f"Bearer {token_empleado}"}
    ).json()
    assert len(notificaciones) == 1
    assert notificaciones[0]["tipo"] == "reserva"


# ---- Transiciones -----------------------------------------------------------------


def test_transicion_invalida_falla(client, admin_headers, cliente_headers, contexto):
    reserva = client.post("/api/v1/reservas", json=_payload_reserva(contexto), headers=cliente_headers).json()

    # No se puede confirmar llegada sin pasar antes por "preparar".
    respuesta = client.put(f"/api/v1/reservas/{reserva['id']}/confirmar-llegada", headers=admin_headers)
    assert respuesta.status_code == 400


def test_preparar_notifica_al_cliente(client, admin_headers, cliente_headers, contexto):
    reserva = client.post("/api/v1/reservas", json=_payload_reserva(contexto), headers=cliente_headers).json()
    client.put(f"/api/v1/reservas/{reserva['id']}/preparar", headers=admin_headers)

    notificaciones = client.get("/api/v1/notificaciones", headers=cliente_headers).json()
    de_esta_reserva = [n for n in notificaciones if n["referencia_id"] == reserva["id"]]
    assert len(de_esta_reserva) == 1
    assert de_esta_reserva[0]["tipo"] == "reserva_preparada"
    assert de_esta_reserva[0]["leida"] is False


def test_flujo_completo_hasta_completada(client, admin_headers, cliente_headers, contexto):
    reserva = client.post("/api/v1/reservas", json=_payload_reserva(contexto), headers=cliente_headers).json()
    reserva_id = reserva["id"]

    preparada = client.put(f"/api/v1/reservas/{reserva_id}/preparar", headers=admin_headers)
    assert preparada.status_code == 200
    assert preparada.json()["estado"] == "preparada"
    assert preparada.json()["detalle"][0]["preparada"] is True

    en_prueba = client.put(f"/api/v1/reservas/{reserva_id}/confirmar-llegada", headers=admin_headers)
    assert en_prueba.status_code == 200
    assert en_prueba.json()["estado"] == "en_prueba"

    variante_id = contexto["variante_id"]
    seleccion = client.put(
        f"/api/v1/reservas/{reserva_id}/seleccion",
        json={"lineas": [{"variante_id": variante_id, "seleccionada": True}]},
        headers=admin_headers,
    )
    assert seleccion.status_code == 200
    assert seleccion.json()["estado"] == "completada"
    assert len(seleccion.json()["historial"]) == 4  # creada, preparada, en_prueba, completada


# ---- Cancelar -----------------------------------------------------------------------


def test_cancelar_reserva_devuelve_disponible(client, admin_headers, cliente_headers, contexto):
    antes = _disponible(client, admin_headers, contexto)
    reserva = client.post("/api/v1/reservas", json=_payload_reserva(contexto, cantidad=2), headers=cliente_headers).json()

    respuesta = client.delete(f"/api/v1/reservas/{reserva['id']}", headers=cliente_headers)
    assert respuesta.status_code == 200
    assert respuesta.json()["estado"] == "cancelada"

    despues = _disponible(client, admin_headers, contexto)
    assert despues == antes


def test_no_se_puede_cancelar_reserva_en_prueba(client, admin_headers, cliente_headers, contexto):
    reserva = client.post("/api/v1/reservas", json=_payload_reserva(contexto), headers=cliente_headers).json()
    client.put(f"/api/v1/reservas/{reserva['id']}/preparar", headers=admin_headers)
    client.put(f"/api/v1/reservas/{reserva['id']}/confirmar-llegada", headers=admin_headers)

    respuesta = client.delete(f"/api/v1/reservas/{reserva['id']}", headers=cliente_headers)
    assert respuesta.status_code == 409


def test_cliente_no_puede_cancelar_reserva_ajena(client, admin_headers, cliente_headers, contexto):
    reserva = client.post("/api/v1/reservas", json=_payload_reserva(contexto), headers=cliente_headers).json()

    client.post(
        "/api/v1/auth/registro",
        json={"nombre": "Otro", "apellido": "Cliente", "email": "otro_cliente@example.com", "password": "claveSegura123"},
    )
    token_otro = client.post(
        "/api/v1/auth/login", json={"email": "otro_cliente@example.com", "password": "claveSegura123"}
    ).json()["access_token"]

    respuesta = client.delete(
        f"/api/v1/reservas/{reserva['id']}", headers={"Authorization": f"Bearer {token_otro}"}
    )
    assert respuesta.status_code == 403


# ---- Selección parcial (el hueco) --------------------------------------------------


def test_seleccion_parcial_libera_solo_lo_no_seleccionado(client, admin_headers, cliente_headers, contexto):
    # Reserva dos variantes distintas del mismo producto para tener dos líneas.
    talla2 = client.post("/api/v1/tallas", json={"codigo": "L", "orden": 2}, headers=admin_headers).json()
    client.post(
        f"/api/v1/productos/{contexto['producto_id']}/variantes",
        json={"tallas_ids": [talla2["id"]], "colores_ids": [contexto["color_id"]]},
        headers=admin_headers,
    )
    variantes = client.get(
        f"/api/v1/productos/{contexto['producto_id']}/variantes", headers=admin_headers
    ).json()
    variante2_id = next(v["id"] for v in variantes if v["id"] != contexto["variante_id"])

    client.post(
        "/api/v1/inventario/movimientos",
        json={
            "variante_id": variante2_id,
            "sucursal_id": contexto["sucursal_id"],
            "tipo_movimiento_codigo": "recepcion",
            "cantidad": 5,
            "costo_unitario": "12.00",
        },
        headers=admin_headers,
    )

    payload = _payload_reserva(contexto)
    payload["detalle"].append({"variante_id": variante2_id, "cantidad": 1})
    reserva = client.post("/api/v1/reservas", json=payload, headers=cliente_headers).json()
    reserva_id = reserva["id"]

    client.put(f"/api/v1/reservas/{reserva_id}/preparar", headers=admin_headers)
    client.put(f"/api/v1/reservas/{reserva_id}/confirmar-llegada", headers=admin_headers)

    disponible_v1_antes = _disponible(client, admin_headers, contexto)
    disponible_v2_antes = client.get(
        f"/api/v1/inventario/stock/{variante2_id}/{contexto['sucursal_id']}", headers=admin_headers
    ).json()["cantidad_disponible"]

    # Selección parcial: solo se decide la variante 1 (rechazada). La
    # variante 2 queda sin decidir en esta llamada.
    respuesta = client.put(
        f"/api/v1/reservas/{reserva_id}/seleccion",
        json={"lineas": [{"variante_id": contexto["variante_id"], "seleccionada": False}]},
        headers=admin_headers,
    )
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["estado"] == "en_prueba"  # no se completa: falta decidir la variante 2

    disponible_v1_despues = _disponible(client, admin_headers, contexto)
    disponible_v2_despues = client.get(
        f"/api/v1/inventario/stock/{variante2_id}/{contexto['sucursal_id']}", headers=admin_headers
    ).json()["cantidad_disponible"]

    assert disponible_v1_despues == disponible_v1_antes + 1  # se liberó
    assert disponible_v2_despues == disponible_v2_antes  # la variante 2 sigue reservada, sin tocar

    # Ahora se decide la variante 2: recién ahí se completa.
    respuesta2 = client.put(
        f"/api/v1/reservas/{reserva_id}/seleccion",
        json={"lineas": [{"variante_id": variante2_id, "seleccionada": True}]},
        headers=admin_headers,
    )
    assert respuesta2.status_code == 200
    assert respuesta2.json()["estado"] == "completada"

    disponible_v2_final = client.get(
        f"/api/v1/inventario/stock/{variante2_id}/{contexto['sucursal_id']}", headers=admin_headers
    ).json()["cantidad_disponible"]
    assert disponible_v2_final == disponible_v2_antes  # seleccionada=True: sigue reservada, no se libera


def test_no_se_puede_reseleccionar_linea_ya_decidida(client, admin_headers, cliente_headers, contexto):
    reserva = client.post("/api/v1/reservas", json=_payload_reserva(contexto, cantidad=2), headers=cliente_headers).json()
    reserva_id = reserva["id"]
    client.put(f"/api/v1/reservas/{reserva_id}/preparar", headers=admin_headers)
    client.put(f"/api/v1/reservas/{reserva_id}/confirmar-llegada", headers=admin_headers)

    variante_id = contexto["variante_id"]
    client.put(
        f"/api/v1/reservas/{reserva_id}/seleccion",
        json={"lineas": [{"variante_id": variante_id, "seleccionada": True}]},
        headers=admin_headers,
    )

    respuesta = client.put(
        f"/api/v1/reservas/{reserva_id}/seleccion",
        json={"lineas": [{"variante_id": variante_id, "seleccionada": False}]},
        headers=admin_headers,
    )
    assert respuesta.status_code == 409


def test_seleccion_solo_valida_en_estado_en_prueba(client, admin_headers, cliente_headers, contexto):
    reserva = client.post("/api/v1/reservas", json=_payload_reserva(contexto), headers=cliente_headers).json()
    respuesta = client.put(
        f"/api/v1/reservas/{reserva['id']}/seleccion",
        json={"lineas": [{"variante_id": contexto["variante_id"], "seleccionada": True}]},
        headers=admin_headers,
    )
    assert respuesta.status_code == 409


# ---- Listados y permisos -----------------------------------------------------------


def test_mis_reservas_solo_devuelve_las_propias(client, admin_headers, cliente_headers, contexto):
    client.post("/api/v1/reservas", json=_payload_reserva(contexto), headers=cliente_headers)

    listado = client.get("/api/v1/reservas/mis-reservas", headers=cliente_headers)
    assert listado.status_code == 200
    assert len(listado.json()) == 1


def test_listar_reservas_sucursal_requiere_permiso_staff(client, cliente_headers, contexto):
    respuesta = client.get(f"/api/v1/reservas/sucursal/{contexto['sucursal_id']}", headers=cliente_headers)
    assert respuesta.status_code == 403


def test_listar_reservas_sucursal_staff_ok(client, admin_headers, cliente_headers, contexto):
    client.post("/api/v1/reservas", json=_payload_reserva(contexto), headers=cliente_headers)
    respuesta = client.get(f"/api/v1/reservas/sucursal/{contexto['sucursal_id']}", headers=admin_headers)
    assert respuesta.status_code == 200
    assert len(respuesta.json()) == 1


# ---- Tarea de expiración ------------------------------------------------------------


def test_expirar_reservas_requiere_token(client):
    respuesta = client.post("/api/v1/tareas/expirar-reservas")
    assert respuesta.status_code == 401


def test_expirar_reservas_libera_stock_y_cambia_estado(client, admin_headers, cliente_headers, contexto, db_session):
    antes = _disponible(client, admin_headers, contexto)
    reserva = client.post("/api/v1/reservas", json=_payload_reserva(contexto, cantidad=2), headers=cliente_headers).json()

    # Fuerza la expiración manipulando directamente fecha_expiracion (no
    # hay forma de crear una reserva ya vencida a través de la API).
    reserva_db = db_session.get(Reserva, reserva["id"])
    reserva_db.fecha_expiracion = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)
    db_session.commit()

    respuesta = client.post(
        "/api/v1/tareas/expirar-reservas", headers={"X-Service-Token": "token-de-pruebas"}
    )
    assert respuesta.status_code == 200
    assert respuesta.json()["expiradas"] == 1

    despues = _disponible(client, admin_headers, contexto)
    assert despues == antes

    detalle = client.get(f"/api/v1/reservas/{reserva['id']}", headers=cliente_headers).json()
    assert detalle["estado"] == "expirada"


def test_expirar_reservas_una_inconsistente_no_frena_a_las_demas(
    client, admin_headers, cliente_headers, contexto, db_session
):
    """Cada reserva vencida es su propia transacción: si una no se puede
    liberar (menos stock reservado del que dice su detalle), se registra y
    se sigue con el resto en vez de trabar la tarea para siempre."""
    from sqlalchemy import update

    from app.inventario.models import Stock
    from app.reservas.politicas import expirar_reservas_vencidas

    rota = client.post("/api/v1/reservas", json=_payload_reserva(contexto, cantidad=2), headers=cliente_headers).json()
    sana = client.post("/api/v1/reservas", json=_payload_reserva(contexto, cantidad=1), headers=cliente_headers).json()
    vencida = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)
    for reserva_id in (rota["id"], sana["id"]):
        db_session.get(Reserva, reserva_id).fecha_expiracion = vencida
    # Desfase: queda 1 unidad reservada en vez de 3 (la primera pide 2).
    db_session.execute(
        update(Stock)
        .where(Stock.variante_id == contexto["variante_id"], Stock.sucursal_id == contexto["sucursal_id"])
        .values(cantidad_reservada=1)
    )
    db_session.commit()

    assert expirar_reservas_vencidas(db_session) == 1

    estados = {
        r["id"]: r["estado"] for r in client.get("/api/v1/reservas/mis-reservas", headers=cliente_headers).json()
    }
    assert estados[rota["id"]] == "pendiente"
    assert estados[sana["id"]] == "expirada"
