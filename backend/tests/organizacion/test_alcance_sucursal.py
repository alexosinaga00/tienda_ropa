"""BE-008: el personal de sucursal (cajero, encargado) solo opera y consulta
su propia sucursal; el administrador (organizacion.gestionar) todas."""

import datetime as dt

import pytest

from app.seguridad.repository import UsuarioRepository
from app.seguridad.schemas import UsuarioCrear
from tests.conftest import _login, crear_cajero


def _crear_staff(client, admin_headers, db_session, *, rol: str, sucursal_id: int, email: str) -> dict:
    repo = UsuarioRepository()
    usuario = repo.crear(db_session, UsuarioCrear(nombre="Staff", apellido=rol, email=email, password="claveSegura123"))
    repo.asignar_roles(db_session, usuario, [rol])
    client.post("/api/v1/empleados", json={"usuario_id": usuario.id, "sucursal_id": sucursal_id}, headers=admin_headers)
    return {"Authorization": f"Bearer {_login(client, email, 'claveSegura123')}"}


def _proxima_fecha_con_dia_semana(dia_semana: int) -> dt.date:
    base = dt.date.today() + dt.timedelta(days=7)
    return base + dt.timedelta(days=(dia_semana - base.isoweekday()) % 7)


@pytest.fixture()
def dos_sucursales(client, admin_headers, db_session):
    cat = client.post("/api/v1/categorias", json={"nombre": "Camisas Alcance"}, headers=admin_headers).json()
    talla = client.post("/api/v1/tallas", json={"codigo": "M", "orden": 1}, headers=admin_headers).json()
    color = client.post("/api/v1/colores", json={"nombre": "Azul Alcance"}, headers=admin_headers).json()
    producto = client.post(
        "/api/v1/productos",
        json={
            "codigo": "ALC-1",
            "nombre": "Camisa alcance",
            "categoria_id": cat["id"],
            "precio_base": "100.00",
            "tallas_ids": [talla["id"]],
            "colores_ids": [color["id"]],
        },
        headers=admin_headers,
    ).json()
    variante_id = client.get(f"/api/v1/productos/{producto['id']}/variantes", headers=admin_headers).json()[0]["id"]
    ciudad = client.post(
        "/api/v1/ciudades", json={"nombre": "Santa Cruz Alcance", "departamento": "Santa Cruz"}, headers=admin_headers
    ).json()

    sucursales = {}
    for codigo in ("A", "B"):
        sucursal = client.post(
            "/api/v1/sucursales",
            json={"ciudad_id": ciudad["id"], "codigo": f"SUC-ALC-{codigo}", "nombre": f"Sucursal {codigo}", "direccion": "Av. 1"},
            headers=admin_headers,
        ).json()
        client.post(
            "/api/v1/inventario/movimientos",
            json={
                "variante_id": variante_id,
                "sucursal_id": sucursal["id"],
                "tipo_movimiento_codigo": "recepcion",
                "cantidad": 10,
                "costo_unitario": "10.00",
            },
            headers=admin_headers,
        )
        client.post(
            f"/api/v1/sucursales/{sucursal['id']}/horarios",
            json={"dia_semana": 3, "hora_apertura": "08:00:00", "hora_cierre": "20:00:00"},
            headers=admin_headers,
        )
        sucursales[codigo] = sucursal["id"]

    return {
        "variante_id": variante_id,
        "a": sucursales["A"],
        "b": sucursales["B"],
        "cajero_a": crear_cajero(client, admin_headers, db_session, sucursal_id=sucursales["A"], email="cajero.a@example.com"),
        "cajero_b": crear_cajero(client, admin_headers, db_session, sucursal_id=sucursales["B"], email="cajero.b@example.com"),
        "encargado_a": _crear_staff(
            client, admin_headers, db_session, rol="encargado_sucursal", sucursal_id=sucursales["A"],
            email="encargado.a@example.com",
        ),
    }


def _venta(client, ctx, sucursal: str, cajero: str):
    return client.post(
        "/api/v1/ventas/presencial",
        json={"sucursal_id": ctx[sucursal], "detalle": [{"variante_id": ctx["variante_id"], "cantidad": 1}]},
        headers=ctx[cajero],
    )


def test_cajero_solo_vende_y_consulta_en_su_sucursal(client, dos_sucursales):
    ctx = dos_sucursales
    assert _venta(client, ctx, "b", "cajero_a").status_code == 403
    assert _venta(client, ctx, "a", "cajero_a").status_code == 201

    assert client.get(f"/api/v1/ventas/sucursal/{ctx['b']}", headers=ctx["cajero_a"]).status_code == 403
    assert client.get(f"/api/v1/ventas/sucursal/{ctx['a']}", headers=ctx["cajero_a"]).status_code == 200


def test_cajero_no_cobra_devuelve_ni_ve_ventas_de_otra_sucursal(client, dos_sucursales):
    ctx = dos_sucursales
    venta_b = _venta(client, ctx, "b", "cajero_b").json()

    cobro = client.post("/api/v1/pagos/caja", json={"venta_id": venta_b["id"], "metodo_pago": "qr"}, headers=ctx["cajero_a"])
    assert cobro.status_code == 403
    assert client.get(f"/api/v1/ventas/{venta_b['id']}/comprobante", headers=ctx["cajero_a"]).status_code == 403

    pagado = client.post("/api/v1/pagos/caja", json={"venta_id": venta_b["id"], "metodo_pago": "qr"}, headers=ctx["cajero_b"])
    assert pagado.status_code == 201
    devolucion = client.post(
        "/api/v1/devoluciones",
        json={"venta_id": venta_b["id"], "detalle": [{"venta_detalle_id": venta_b["detalle"][0]["id"], "cantidad": 1}]},
        headers=ctx["cajero_a"],
    )
    assert devolucion.status_code == 403
    anular = client.post(f"/api/v1/pagos/{pagado.json()['pago']['id']}/anular", headers=ctx["cajero_a"])
    assert anular.status_code == 403


def test_encargado_solo_ve_y_mueve_inventario_de_su_sucursal(client, admin_headers, dos_sucursales):
    ctx = dos_sucursales

    consolidado = client.get("/api/v1/inventario/consolidado", headers=ctx["encargado_a"])
    assert consolidado.status_code == 200
    assert {fila["sucursal_id"] for fila in consolidado.json()} == {ctx["a"]}
    assert client.get(f"/api/v1/inventario/consolidado?sucursal_id={ctx['b']}", headers=ctx["encargado_a"]).status_code == 403

    ajuste = {"variante_id": ctx["variante_id"], "cantidad": -1, "observacion": "rotura"}
    assert client.post("/api/v1/inventario/ajustes", json={**ajuste, "sucursal_id": ctx["b"]}, headers=ctx["encargado_a"]).status_code == 403
    assert client.post("/api/v1/inventario/ajustes", json={**ajuste, "sucursal_id": ctx["a"]}, headers=ctx["encargado_a"]).status_code == 201

    # El administrador sigue viendo todas.
    todas = client.get("/api/v1/inventario/consolidado", headers=admin_headers).json()
    assert {fila["sucursal_id"] for fila in todas} == {ctx["a"], ctx["b"]}


def test_encargado_no_ve_ni_atiende_reservas_de_otra_sucursal(client, cliente_headers, dos_sucursales):
    ctx = dos_sucursales
    reserva_b = client.post(
        "/api/v1/reservas",
        json={
            "sucursal_id": ctx["b"],
            "fecha_visita": _proxima_fecha_con_dia_semana(3).isoformat(),
            "hora_visita_desde": "10:00:00",
            "hora_visita_hasta": "11:00:00",
            "detalle": [{"variante_id": ctx["variante_id"], "cantidad": 1}],
        },
        headers=cliente_headers,
    ).json()

    assert client.get(f"/api/v1/reservas/sucursal/{ctx['b']}", headers=ctx["encargado_a"]).status_code == 403
    assert client.get(f"/api/v1/reservas/{reserva_b['id']}", headers=ctx["encargado_a"]).status_code == 403
    assert client.put(f"/api/v1/reservas/{reserva_b['id']}/preparar", headers=ctx["encargado_a"]).status_code == 403
    assert client.delete(f"/api/v1/reservas/{reserva_b['id']}", headers=ctx["encargado_a"]).status_code == 403
    assert client.get(f"/api/v1/reservas/sucursal/{ctx['a']}", headers=ctx["encargado_a"]).status_code == 200


def test_encargado_ve_reportes_solo_de_su_sucursal(client, dos_sucursales):
    ctx = dos_sucursales
    assert client.get(f"/api/v1/reportes/reservas?sucursal_id={ctx['b']}", headers=ctx["encargado_a"]).status_code == 403

    inventario = client.get("/api/v1/reportes/inventario", headers=ctx["encargado_a"])
    assert inventario.status_code == 200
    assert {fila["sucursal_id"] for fila in inventario.json()["consolidado"]} == {ctx["a"]}
