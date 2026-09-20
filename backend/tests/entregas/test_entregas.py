import pytest

from app.ventas.politicas import anular_venta, confirmar_venta
from tests.conftest import crear_cajero, crear_staff


@pytest.fixture()
def zona_1er_anillo(client):
    zonas = client.get("/api/v1/zonas-envio").json()
    return next(z for z in zonas if z["nombre"] == "1er anillo")


@pytest.fixture()
def contexto(client, admin_headers):
    cat = client.post("/api/v1/categorias", json={"nombre": "Camisas Entrega"}, headers=admin_headers).json()
    talla = client.post("/api/v1/tallas", json={"codigo": "M", "orden": 1}, headers=admin_headers).json()
    color = client.post("/api/v1/colores", json={"nombre": "Azul Entrega"}, headers=admin_headers).json()
    producto = client.post(
        "/api/v1/productos",
        json={
            "codigo": "ENT-1",
            "nombre": "Camisa entrega",
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
        "/api/v1/ciudades", json={"nombre": "Santa Cruz Entrega", "departamento": "Santa Cruz"}, headers=admin_headers
    ).json()
    sucursal = client.post(
        "/api/v1/sucursales",
        json={"ciudad_id": ciudad["id"], "codigo": "SUC-ENT", "nombre": "Sucursal Entrega", "direccion": "Av. 1"},
        headers=admin_headers,
    ).json()
    sucursal_id = sucursal["id"]

    client.post(
        "/api/v1/inventario/movimientos",
        json={
            "variante_id": variante_id,
            "sucursal_id": sucursal_id,
            "tipo_movimiento_codigo": "recepcion",
            "cantidad": 50,
            "costo_unitario": "10.00",
        },
        headers=admin_headers,
    )

    return {"variante_id": variante_id, "sucursal_id": sucursal_id}


def _crear_direccion(client, cliente_headers, zona_id):
    return client.post(
        "/api/v1/clientes/direcciones",
        json={"zona_envio_id": zona_id, "direccion": "Calle Falsa 123"},
        headers=cliente_headers,
    ).json()


# ---- cálculo de tarifa por anillo, con y sin recargo por peso (Revisar) ----------------


def test_cotizar_sin_recargo_por_peso(client, cliente_headers, zona_1er_anillo):
    direccion = _crear_direccion(client, cliente_headers, zona_1er_anillo["id"])

    # peso_promedio_prenda_kg=0.3 (default) * 5 = 1.5kg, dentro de la
    # franja 0-2kg de regla_tarifa_envio: sin recargo.
    respuesta = client.post("/api/v1/envios/cotizar", json={"direccion_id": direccion["id"], "cantidad_prendas": 5})
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["peso_kg"] == "1.5"
    assert cuerpo["recargo_peso"] == "0.00"
    assert cuerpo["costo"] == zona_1er_anillo["tarifa_base"]


def test_cotizar_con_recargo_por_peso(client, cliente_headers, zona_1er_anillo):
    direccion = _crear_direccion(client, cliente_headers, zona_1er_anillo["id"])

    # 0.3 * 20 = 6.0kg, cae en la franja 5kg+ (recargo 10.00).
    respuesta = client.post("/api/v1/envios/cotizar", json={"direccion_id": direccion["id"], "cantidad_prendas": 20})
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["peso_kg"] == "6.0"
    assert cuerpo["recargo_peso"] == "10.00"
    assert float(cuerpo["costo"]) == float(zona_1er_anillo["tarifa_base"]) + 10.00


def test_cotizar_no_persiste_nada(client, db_session, cliente_headers, zona_1er_anillo):
    from app.entregas.models import Envio

    direccion = _crear_direccion(client, cliente_headers, zona_1er_anillo["id"])
    antes = db_session.query(Envio).count()

    for _ in range(3):
        respuesta = client.post(
            "/api/v1/envios/cotizar", json={"direccion_id": direccion["id"], "cantidad_prendas": 8}
        )
        assert respuesta.status_code == 200

    despues = db_session.query(Envio).count()
    assert despues == antes == 0


# ---- crear envío: el costo de la venta tiene que coincidir con la tarifa real -----------


def test_crear_envio_usa_costo_ya_fijado_en_la_venta(client, cliente_headers, contexto, zona_1er_anillo):
    direccion = _crear_direccion(client, cliente_headers, zona_1er_anillo["id"])
    cotizacion = client.post(
        "/api/v1/envios/cotizar", json={"direccion_id": direccion["id"], "cantidad_prendas": 2}
    ).json()

    client.post(
        "/api/v1/carrito", json={"variante_id": contexto["variante_id"], "cantidad": 2}, headers=cliente_headers
    )
    venta = client.post(
        "/api/v1/ventas/digital",
        json={"sucursal_id": contexto["sucursal_id"], "costo_envio": cotizacion["costo"]},
        headers=cliente_headers,
    ).json()
    assert venta["costo_envio"] == cotizacion["costo"]

    respuesta = client.post(
        "/api/v1/envios", json={"venta_id": venta["id"], "direccion_id": direccion["id"]}, headers=cliente_headers
    )
    assert respuesta.status_code == 201
    envio = respuesta.json()
    assert envio["costo"] == cotizacion["costo"]
    assert envio["zona_envio_id"] == zona_1er_anillo["id"]
    assert envio["estado"] == "programado"

    # no se puede crear un segundo envío para la misma venta
    segundo = client.post(
        "/api/v1/envios", json={"venta_id": venta["id"], "direccion_id": direccion["id"]}, headers=cliente_headers
    )
    assert segundo.status_code == 409


@pytest.mark.parametrize("costo_envio", ["0.01", "0.00"])
def test_crear_envio_rechaza_costo_distinto_a_la_tarifa(
    client, db_session, cliente_headers, contexto, zona_1er_anillo, costo_envio
):
    """El costo de envío de la venta lo manda el cliente: si no coincide con
    la tarifa real de la zona, no hay envío (ni pagando de menos ni con una
    compra registrada como retiro en sucursal)."""
    from app.entregas.models import Envio

    assert float(zona_1er_anillo["tarifa_base"]) > 0
    direccion = _crear_direccion(client, cliente_headers, zona_1er_anillo["id"])
    client.post(
        "/api/v1/carrito", json={"variante_id": contexto["variante_id"], "cantidad": 1}, headers=cliente_headers
    )
    venta = client.post(
        "/api/v1/ventas/digital",
        json={"sucursal_id": contexto["sucursal_id"], "costo_envio": costo_envio},
        headers=cliente_headers,
    ).json()

    respuesta = client.post(
        "/api/v1/envios", json={"venta_id": venta["id"], "direccion_id": direccion["id"]}, headers=cliente_headers
    )
    # 400 y no 409: los clientes toman un 409 acá como "el envío ya existía".
    assert respuesta.status_code == 400
    assert "no coincide con la tarifa" in respuesta.json()["detail"]
    assert db_session.query(Envio).filter(Envio.venta_id == venta["id"]).count() == 0


# ---- máquina de estados del envío -------------------------------------------------------


def _crear_envio(client, admin_headers, cliente_headers, contexto, zona_1er_anillo):
    direccion = _crear_direccion(client, cliente_headers, zona_1er_anillo["id"])
    cotizacion = client.post(
        "/api/v1/envios/cotizar", json={"direccion_id": direccion["id"], "cantidad_prendas": 1}
    ).json()
    client.post(
        "/api/v1/carrito", json={"variante_id": contexto["variante_id"], "cantidad": 1}, headers=cliente_headers
    )
    venta = client.post(
        "/api/v1/ventas/digital",
        json={"sucursal_id": contexto["sucursal_id"], "costo_envio": cotizacion["costo"]},
        headers=cliente_headers,
    ).json()
    return client.post(
        "/api/v1/envios", json={"venta_id": venta["id"], "direccion_id": direccion["id"]}, headers=cliente_headers
    ).json()


def _pagar_venta(db_session, venta_id):
    """Lo que hace `pagos` al aprobar el pago: la venta pasa a 'pagada'."""
    confirmar_venta(db_session, venta_id)


def _estado_venta(client, headers, venta_id):
    return client.get(f"/api/v1/ventas/{venta_id}/comprobante", headers=headers).json()["estado"]


def _cambiar_estado(client, headers, envio_id, estado, **extra):
    return client.put(f"/api/v1/envios/{envio_id}/estado", json={"estado": estado, **extra}, headers=headers)


def test_no_se_puede_saltar_directo_a_entregado(client, admin_headers, cliente_headers, contexto, zona_1er_anillo):
    envio = _crear_envio(client, admin_headers, cliente_headers, contexto, zona_1er_anillo)

    respuesta = client.put(f"/api/v1/envios/{envio['id']}/estado", json={"estado": "entregado"}, headers=admin_headers)
    assert respuesta.status_code == 409


def test_ciclo_completo_hasta_entregado(
    client, db_session, admin_headers, cliente_headers, contexto, zona_1er_anillo
):
    envio = _crear_envio(client, admin_headers, cliente_headers, contexto, zona_1er_anillo)
    _pagar_venta(db_session, envio["venta_id"])

    en_ruta = client.put(
        f"/api/v1/envios/{envio['id']}/estado",
        json={"estado": "en_ruta", "repartidor": "Juan Perez"},
        headers=admin_headers,
    )
    assert en_ruta.status_code == 200
    cuerpo = en_ruta.json()
    assert cuerpo["repartidor"] == "Juan Perez"
    assert cuerpo["fecha_programada"] is not None
    assert cuerpo["fecha_entrega"] is None

    entregado = client.put(f"/api/v1/envios/{envio['id']}/estado", json={"estado": "entregado"}, headers=admin_headers)
    assert entregado.status_code == 200
    assert entregado.json()["fecha_entrega"] is not None

    # 'entregado' es terminal
    otro = client.put(f"/api/v1/envios/{envio['id']}/estado", json={"estado": "en_ruta"}, headers=admin_headers)
    assert otro.status_code == 409


def test_entregado_deja_la_venta_entregada(client, db_session, admin_headers, cliente_headers, contexto, zona_1er_anillo):
    envio = _crear_envio(client, admin_headers, cliente_headers, contexto, zona_1er_anillo)
    _pagar_venta(db_session, envio["venta_id"])
    assert _estado_venta(client, admin_headers, envio["venta_id"]) == "pagada"

    assert _cambiar_estado(client, admin_headers, envio["id"], "en_ruta").status_code == 200
    assert _estado_venta(client, admin_headers, envio["venta_id"]) == "pagada"  # en camino, todavía no llegó

    assert _cambiar_estado(client, admin_headers, envio["id"], "entregado").status_code == 200
    assert _estado_venta(client, admin_headers, envio["venta_id"]) == "entregada"


def test_no_se_despacha_un_envio_de_una_venta_sin_pagar(client, admin_headers, cliente_headers, contexto, zona_1er_anillo):
    envio = _crear_envio(client, admin_headers, cliente_headers, contexto, zona_1er_anillo)

    respuesta = _cambiar_estado(client, admin_headers, envio["id"], "en_ruta")
    assert respuesta.status_code == 409
    assert "pendiente_pago" in respuesta.json()["detail"]
    assert client.get(f"/api/v1/envios/{envio['id']}", headers=admin_headers).json()["estado"] == "programado"


def test_fallido_desde_en_ruta_no_toca_la_venta(client, db_session, admin_headers, cliente_headers, contexto, zona_1er_anillo):
    envio = _crear_envio(client, admin_headers, cliente_headers, contexto, zona_1er_anillo)
    _pagar_venta(db_session, envio["venta_id"])
    _cambiar_estado(client, admin_headers, envio["id"], "en_ruta")

    respuesta = _cambiar_estado(client, admin_headers, envio["id"], "fallido")
    assert respuesta.status_code == 200
    assert respuesta.json()["estado"] == "fallido"
    assert respuesta.json()["fecha_entrega"] is None
    assert _estado_venta(client, admin_headers, envio["venta_id"]) == "pagada"

    # 'fallido' es terminal
    assert _cambiar_estado(client, admin_headers, envio["id"], "en_ruta").status_code == 409
    assert _cambiar_estado(client, admin_headers, envio["id"], "entregado").status_code == 409


def test_fallido_desde_programado_y_con_la_venta_anulada(
    client, db_session, admin_headers, cliente_headers, contexto, zona_1er_anillo
):
    envio = _crear_envio(client, admin_headers, cliente_headers, contexto, zona_1er_anillo)
    anular_venta(db_session, envio["venta_id"])

    # Un envío de una venta anulada no se puede despachar, pero sí cerrar.
    assert _cambiar_estado(client, admin_headers, envio["id"], "en_ruta").status_code == 409
    respuesta = _cambiar_estado(client, admin_headers, envio["id"], "fallido")
    assert respuesta.status_code == 200
    assert respuesta.json()["estado"] == "fallido"


def test_actualizar_un_envio_inexistente_da_404(client, admin_headers):
    assert _cambiar_estado(client, admin_headers, 99999, "en_ruta").status_code == 404


def test_solo_el_personal_con_permiso_actualiza_envios(
    client, db_session, admin_headers, cliente_headers, contexto, zona_1er_anillo
):
    envio = _crear_envio(client, admin_headers, cliente_headers, contexto, zona_1er_anillo)
    _pagar_venta(db_session, envio["venta_id"])
    cajero = crear_cajero(client, admin_headers, db_session, sucursal_id=contexto["sucursal_id"])

    assert _cambiar_estado(client, cliente_headers, envio["id"], "en_ruta").status_code == 403
    assert _cambiar_estado(client, cajero, envio["id"], "en_ruta").status_code == 403  # sin entregas.gestionar
    assert client.get("/api/v1/envios", headers=cliente_headers).status_code == 403


def _otra_sucursal(client, admin_headers):
    ciudad = client.post(
        "/api/v1/ciudades", json={"nombre": "Cochabamba Entrega", "departamento": "Cochabamba"}, headers=admin_headers
    ).json()
    return client.post(
        "/api/v1/sucursales",
        json={"ciudad_id": ciudad["id"], "codigo": "SUC-ENT-B", "nombre": "Sucursal B", "direccion": "Av. 2"},
        headers=admin_headers,
    ).json()["id"]


def _encargado(client, admin_headers, db_session, sucursal_id, email):
    return crear_staff(
        client, admin_headers, db_session, rol="encargado_sucursal", cargo="Encargado", sucursal_id=sucursal_id, email=email
    )


def test_el_encargado_solo_mueve_envios_de_su_sucursal(
    client, db_session, admin_headers, cliente_headers, contexto, zona_1er_anillo
):
    envio = _crear_envio(client, admin_headers, cliente_headers, contexto, zona_1er_anillo)
    _pagar_venta(db_session, envio["venta_id"])
    propio = _encargado(client, admin_headers, db_session, contexto["sucursal_id"], "enc.a@example.com")
    ajeno = _encargado(client, admin_headers, db_session, _otra_sucursal(client, admin_headers), "enc.b@example.com")

    assert _cambiar_estado(client, ajeno, envio["id"], "en_ruta").status_code == 403
    assert _cambiar_estado(client, propio, envio["id"], "en_ruta", repartidor="Ana").status_code == 200
    assert _cambiar_estado(client, propio, envio["id"], "entregado").status_code == 200


def test_listar_envios_acotado_por_sucursal_y_por_estado(
    client, db_session, admin_headers, cliente_headers, contexto, zona_1er_anillo
):
    envio = _crear_envio(client, admin_headers, cliente_headers, contexto, zona_1er_anillo)
    propio = _encargado(client, admin_headers, db_session, contexto["sucursal_id"], "enc.a@example.com")
    ajeno = _encargado(client, admin_headers, db_session, _otra_sucursal(client, admin_headers), "enc.b@example.com")

    assert [e["id"] for e in client.get("/api/v1/envios", headers=propio).json()] == [envio["id"]]
    assert client.get("/api/v1/envios", headers=ajeno).json() == []
    # Pedir otra sucursal siendo de sucursal propia: 403, no un listado vacío.
    assert client.get(f"/api/v1/envios?sucursal_id={contexto['sucursal_id']}", headers=ajeno).status_code == 403

    # El administrador (alcance global) ve todo y puede filtrar.
    assert [e["id"] for e in client.get("/api/v1/envios", headers=admin_headers).json()] == [envio["id"]]
    por_sucursal = client.get(f"/api/v1/envios?sucursal_id={contexto['sucursal_id']}", headers=admin_headers)
    assert [e["id"] for e in por_sucursal.json()] == [envio["id"]]
    assert client.get("/api/v1/envios?estado=programado", headers=admin_headers).json() != []
    assert client.get("/api/v1/envios?estado=en_ruta", headers=admin_headers).json() == []


def test_consultar_un_envio_por_id_y_por_venta(client, admin_headers, cliente_headers, contexto, zona_1er_anillo):
    envio = _crear_envio(client, admin_headers, cliente_headers, contexto, zona_1er_anillo)

    for headers in (cliente_headers, admin_headers):
        por_id = client.get(f"/api/v1/envios/{envio['id']}", headers=headers)
        por_venta = client.get(f"/api/v1/envios/venta/{envio['venta_id']}", headers=headers)
        assert por_id.status_code == 200 and por_venta.status_code == 200
        assert por_id.json() == por_venta.json()
        assert por_id.json()["estado"] == "programado"

    client.post(
        "/api/v1/auth/registro",
        json={"nombre": "Otro", "apellido": "Cliente", "email": "otro@example.com", "password": "claveSegura123"},
    )
    token = client.post("/api/v1/auth/login", json={"email": "otro@example.com", "password": "claveSegura123"})
    otro = {"Authorization": f"Bearer {token.json()['access_token']}"}
    assert client.get(f"/api/v1/envios/{envio['id']}", headers=otro).status_code == 403
    assert client.get(f"/api/v1/envios/venta/{envio['venta_id']}", headers=otro).status_code == 403
    assert client.get("/api/v1/envios/99999", headers=admin_headers).status_code == 404


# ---- aviso al cliente cuando cambia el estado del envío -----------------------------------


def _notificaciones(client, headers):
    return client.get("/api/v1/notificaciones", headers=headers).json()


def _codigo_de_venta(client, headers, venta_id):
    return client.get(f"/api/v1/ventas/{venta_id}/comprobante", headers=headers).json()["codigo"]


def test_cada_estado_del_envio_le_avisa_al_cliente(
    client, db_session, admin_headers, cliente_headers, contexto, zona_1er_anillo
):
    envio = _crear_envio(client, admin_headers, cliente_headers, contexto, zona_1er_anillo)
    _pagar_venta(db_session, envio["venta_id"])
    codigo = _codigo_de_venta(client, cliente_headers, envio["venta_id"])
    assert _notificaciones(client, cliente_headers) == []

    assert _cambiar_estado(client, admin_headers, envio["id"], "en_ruta").status_code == 200
    (en_camino,) = _notificaciones(client, cliente_headers)
    assert en_camino["titulo"] == "Tu pedido está en camino"
    assert codigo in en_camino["mensaje"]
    assert en_camino["tipo"] == "envio"
    assert en_camino["referencia_id"] == envio["venta_id"]  # la app abre la compra con este id
    assert en_camino["leida"] is False

    assert _cambiar_estado(client, admin_headers, envio["id"], "entregado").status_code == 200
    titulos = [n["titulo"] for n in _notificaciones(client, cliente_headers)]
    assert titulos == ["Tu pedido fue entregado", "Tu pedido está en camino"]  # la más reciente primero


def test_un_envio_fallido_tambien_le_avisa_al_cliente(
    client, db_session, admin_headers, cliente_headers, contexto, zona_1er_anillo
):
    envio = _crear_envio(client, admin_headers, cliente_headers, contexto, zona_1er_anillo)
    _pagar_venta(db_session, envio["venta_id"])

    assert _cambiar_estado(client, admin_headers, envio["id"], "fallido").status_code == 200

    (aviso,) = _notificaciones(client, cliente_headers)
    assert aviso["titulo"] == "No pudimos entregar tu pedido"
    assert aviso["tipo"] == "envio"
    assert aviso["referencia_id"] == envio["venta_id"]


def test_el_aviso_del_envio_es_solo_del_dueno_de_la_compra(
    client, db_session, admin_headers, cliente_headers, contexto, zona_1er_anillo
):
    envio = _crear_envio(client, admin_headers, cliente_headers, contexto, zona_1er_anillo)
    _pagar_venta(db_session, envio["venta_id"])
    client.post(
        "/api/v1/auth/registro",
        json={"nombre": "Otro", "apellido": "Cliente", "email": "otro.aviso@example.com", "password": "claveSegura123"},
    )
    token = client.post("/api/v1/auth/login", json={"email": "otro.aviso@example.com", "password": "claveSegura123"})
    otro = {"Authorization": f"Bearer {token.json()['access_token']}"}

    _cambiar_estado(client, admin_headers, envio["id"], "en_ruta")

    assert len(_notificaciones(client, cliente_headers)) == 1
    assert _notificaciones(client, otro) == []
    assert _notificaciones(client, admin_headers) == []  # el personal no recibe el aviso del cliente


def test_un_cambio_rechazado_no_deja_ningun_aviso(client, admin_headers, cliente_headers, contexto, zona_1er_anillo):
    envio = _crear_envio(client, admin_headers, cliente_headers, contexto, zona_1er_anillo)

    # Venta sin pagar: no se puede despachar (409), y el cliente no debe recibir "en camino".
    assert _cambiar_estado(client, admin_headers, envio["id"], "en_ruta").status_code == 409
    # Salto de estado inválido (409).
    assert _cambiar_estado(client, admin_headers, envio["id"], "entregado").status_code == 409

    assert _notificaciones(client, cliente_headers) == []


def test_marcar_como_leida_la_notificacion_del_envio(
    client, db_session, admin_headers, cliente_headers, contexto, zona_1er_anillo
):
    envio = _crear_envio(client, admin_headers, cliente_headers, contexto, zona_1er_anillo)
    _pagar_venta(db_session, envio["venta_id"])
    _cambiar_estado(client, admin_headers, envio["id"], "en_ruta")
    (aviso,) = _notificaciones(client, cliente_headers)

    marcada = client.put(f"/api/v1/notificaciones/{aviso['id']}/leida", headers=cliente_headers)

    assert marcada.status_code == 200
    assert marcada.json()["leida"] is True
    assert _notificaciones(client, cliente_headers)[0]["leida"] is True
