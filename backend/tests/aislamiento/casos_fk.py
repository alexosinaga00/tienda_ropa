"""E05, 4.4: los campos *_id que llegan en el cuerpo (o en el formulario) de una petición.

Cada caso trae un cuerpo VÁLIDO para A y el campo que se cambia, UNO por vez, por un id de B.
Una FK de la base, por sí sola, permitiría apuntar a otra empresa: por eso cada id se resuelve
con una búsqueda filtrada (404) ANTES de guardarse. La prueba exige 404, que no se cree ni
cambie nada y que, con ids propios, la misma petición funcione.
"""

import datetime as dt
import io
import uuid
from typing import Callable, NamedTuple

from PIL import Image
from sqlalchemy import select

from app.comercial.models import EstadoReserva, Reserva

from .universo import Universo, crear


def _png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGBA", (16, 16), (200, 30, 30, 255)).save(buffer, "PNG")
    return buffer.getvalue()


PNG = _png()
API = "/api/v1"


class CasoFK(NamedTuple):
    nombre: str
    metodo: str
    ruta: str  # con {clave} del universo de A (se rellena con `Universo.ids`) o callable(a)->str
    cuerpo: Callable[[Universo], dict]  # cuerpo válido para A
    campo: tuple  # camino al id dentro del cuerpo, p. ej. ("detalle", 0, "variante_id")
    ajeno: str  # clave en `Universo.ids` de B
    token: str = "admin"
    multipart: bool = False  # el cuerpo va como formulario con un archivo
    espejo: bool = True  # False: no se ejecuta la petición positiva (servicio externo)
    prepara: Callable[[Universo], None] | None = None


def _ruta(caso: CasoFK, a: Universo) -> str:
    return API + (caso.ruta(a) if callable(caso.ruta) else caso.ruta.format(**a.ids))


# --- piezas reutilizables --------------------------------------------------------------------


def _orden_enviada(a: Universo) -> int:
    orden = a.nuevo("orden_compra")
    crear(a.client, f"/ordenes-compra/{orden}/enviar", None, a.admin)
    return orden


def _reserva_en_prueba(a: Universo) -> int:
    reserva = a.nuevo("reserva")
    with a.orm() as db:
        estado = db.scalar(select(EstadoReserva).where(EstadoReserva.codigo == "en_prueba"))
        db.get(Reserva, reserva).estado_id = estado.id
    return reserva


def _dia_libre(a: Universo) -> str:
    return (dt.date.today() + dt.timedelta(days=40 + a.n())).isoformat()


def _producto(a: Universo) -> dict:
    return {
        "codigo": f"FK-{a.n():04d}",
        "nombre": "Producto FK",
        "categoria_id": a.ids["categoria"],
        "material_id": a.ids["material"],
        "temporada_id": a.ids["temporada"],
        "coleccion_id": a.ids["coleccion"],
        "precio_base": "10.00",
        "tallas_ids": [a.ids["talla"]],
        "colores_ids": [a.ids["color"]],
    }


def _promocion(a: Universo, alcance: dict) -> dict:
    hoy = dt.date.today()
    return {
        "nombre": f"Promo FK {a.n()}",
        "tipo": "porcentaje",
        "valor": "5",
        "fecha_inicio": hoy.isoformat(),
        "fecha_fin": (hoy + dt.timedelta(days=10)).isoformat(),
        "alcances": [alcance],
    }


def _venta_presencial(a: Universo, **extra) -> dict:
    return {
        "sucursal_id": a.ids["sucursal"],
        "cliente_id": a.ids["cliente"],
        "detalle": [{"variante_id": a.ids["variante"], "cantidad": 1}],
        **extra,
    }


def _linea_devolucion(a: Universo) -> dict:
    return {"venta_id": a.ids["venta"], "motivo": "FK", "detalle": [{"venta_detalle_id": a.ids["venta_detalle"], "cantidad": 1}]}


def _solicitud_cambio(a: Universo) -> dict:
    return {
        "venta_id": a.ids["venta"],
        "motivo": "FK",
        "detalle": [{"venta_detalle_id": a.ids["venta_detalle"], "cantidad": 1, "variante_nueva_id": a.ids["variante"]}],
    }


def _pedido_diferido(a: Universo) -> dict:
    return {
        "operacion_id": str(uuid.uuid4()),
        "sucursal_id": a.ids["sucursal"],
        "costo_envio": "0.00",
        "lineas": [{"variante_id": a.ids["variante"], "cantidad": 1}],
        "total_maximo": "99999.00",
    }


def _carrito_con_prenda(a: Universo) -> dict:
    variante = a.nuevo("variante")
    crear(a.client, "/inventario/ajustes", {"variante_id": variante, "sucursal_id": a.ids["sucursal"], "cantidad": 5}, a.admin)
    crear(a.client, "/carrito", {"variante_id": variante, "cantidad": 1}, a.headers["cliente"])
    return {"sucursal_id": a.ids["sucursal"]}


# --- los casos -----------------------------------------------------------------------------------

CASOS_FK: list[CasoFK] = [
    # plataforma
    CasoFK("sucursal.ciudad_id (crear)", "POST", "/sucursales",
           lambda a: {"ciudad_id": a.ids["ciudad"], "codigo": f"F{a.n()}", "nombre": "Sucursal FK", "direccion": "Calle"},
           ("ciudad_id",), "ciudad"),
    CasoFK("sucursal.ciudad_id (actualizar)", "PUT", "/sucursales/{sucursal_destino}",
           lambda a: {"ciudad_id": a.ids["ciudad"]}, ("ciudad_id",), "ciudad"),
    CasoFK("empleado.usuario_id", "POST", "/empleados",
           lambda a: {"usuario_id": a.nuevo("usuario"), "sucursal_id": a.ids["sucursal"]}, ("usuario_id",), "usuario"),
    CasoFK("empleado.sucursal_id (crear)", "POST", "/empleados",
           lambda a: {"usuario_id": a.nuevo("usuario"), "sucursal_id": a.ids["sucursal"]}, ("sucursal_id",), "sucursal"),
    CasoFK("empleado.sucursal_id (actualizar)", "PUT", "/empleados/{empleado}",
           lambda a: {"sucursal_id": a.ids["sucursal_destino"]}, ("sucursal_id",), "sucursal"),
    # catalogo: maestros y productos
    CasoFK("categoria.categoria_padre_id (crear)", "POST", "/categorias",
           lambda a: {"nombre": f"Cat FK {a.n()}", "categoria_padre_id": a.ids["categoria_padre"]}, ("categoria_padre_id",), "categoria"),
    CasoFK("categoria.categoria_padre_id (actualizar)", "PUT", "/categorias/{categoria}",
           lambda a: {"categoria_padre_id": a.ids["categoria_padre"]}, ("categoria_padre_id",), "categoria"),
    CasoFK("coleccion.temporada_id (crear)", "POST", "/colecciones",
           lambda a: {"nombre": f"Col FK {a.n()}", "temporada_id": a.ids["temporada"]}, ("temporada_id",), "temporada"),
    CasoFK("coleccion.temporada_id (actualizar)", "PUT", "/colecciones/{coleccion}",
           lambda a: {"temporada_id": a.ids["temporada"]}, ("temporada_id",), "temporada"),
    *[
        CasoFK(f"producto.{campo} (crear)", "POST", "/productos", _producto, (campo,), recurso)
        for campo, recurso in (
            ("categoria_id", "categoria"),
            ("material_id", "material"),
            ("temporada_id", "temporada"),
            ("coleccion_id", "coleccion"),
            ("tallas_ids", "talla"),
            ("colores_ids", "color"),
        )
    ],
    *[
        CasoFK(f"producto.{campo} (actualizar)", "PUT", "/productos/{producto}",
               lambda a, campo=campo, recurso=recurso: {campo: a.ids[recurso]}, (campo,), recurso)
        for campo, recurso in (
            ("categoria_id", "categoria"),
            ("material_id", "material"),
            ("temporada_id", "temporada"),
            ("coleccion_id", "coleccion"),
        )
    ],
    CasoFK("variantes.tallas_ids", "POST", "/productos/{producto}/variantes",
           lambda a: {"tallas_ids": [a.nuevo("talla")], "colores_ids": [a.nuevo("color")]}, ("tallas_ids",), "talla"),
    CasoFK("variantes.colores_ids", "POST", "/productos/{producto}/variantes",
           lambda a: {"tallas_ids": [a.nuevo("talla")], "colores_ids": [a.nuevo("color")]}, ("colores_ids",), "color"),
    CasoFK("tabla_medida.talla_id (crear)", "POST", "/productos/{producto}/medidas",
           lambda a: {"talla_id": a.nuevo("talla"), "pecho_min_cm": "85"}, ("talla_id",), "talla"),
    CasoFK("tabla_medida.talla_id (actualizar)", "PUT", "/productos/{producto}/medidas/{medida}",
           lambda a: {"talla_id": a.ids["talla"]}, ("talla_id",), "talla"),
    CasoFK("favorito.variante_id", "POST", "/favoritos",
           lambda a: {"variante_id": a.nuevo("variante")}, ("variante_id",), "variante", token="cliente"),
    # catalogo: inventario y abastecimiento
    CasoFK("movimiento.variante_id", "POST", "/inventario/movimientos",
           lambda a: {"variante_id": a.ids["variante"], "sucursal_id": a.ids["sucursal"], "tipo_movimiento_codigo": "ajuste_positivo", "cantidad": 1},
           ("variante_id",), "variante"),
    CasoFK("movimiento.sucursal_id", "POST", "/inventario/movimientos",
           lambda a: {"variante_id": a.ids["variante"], "sucursal_id": a.ids["sucursal"], "tipo_movimiento_codigo": "ajuste_positivo", "cantidad": 1},
           ("sucursal_id",), "sucursal"),
    CasoFK("ajuste.variante_id", "POST", "/inventario/ajustes",
           lambda a: {"variante_id": a.ids["variante"], "sucursal_id": a.ids["sucursal"], "cantidad": 1}, ("variante_id",), "variante"),
    CasoFK("ajuste.sucursal_id", "POST", "/inventario/ajustes",
           lambda a: {"variante_id": a.ids["variante"], "sucursal_id": a.ids["sucursal"], "cantidad": 1}, ("sucursal_id",), "sucursal"),
    *[
        CasoFK(f"transferencia.{nombre}", "POST", "/transferencias",
               lambda a: {
                   "codigo": f"TF{a.n():04d}",
                   "sucursal_origen_id": a.ids["sucursal"],
                   "sucursal_destino_id": a.ids["sucursal_destino"],
                   "detalle": [{"variante_id": a.ids["variante"], "cantidad": 1}],
               },
               campo, recurso)
        for nombre, campo, recurso in (
            ("sucursal_origen_id", ("sucursal_origen_id",), "sucursal"),
            ("sucursal_destino_id", ("sucursal_destino_id",), "sucursal"),
            ("detalle.variante_id", ("detalle", 0, "variante_id"), "variante"),
        )
    ],
    CasoFK("proveedor.usuario_id (crear)", "POST", "/proveedores",
           lambda a: {"nombre": f"Prov FK {a.n()}", "usuario_id": a.nuevo("usuario")}, ("usuario_id",), "usuario"),
    CasoFK("proveedor.usuario_id (actualizar)", "PUT", "/proveedores/{proveedor}",
           lambda a: {"usuario_id": a.nuevo("usuario")}, ("usuario_id",), "usuario"),
    CasoFK("producto_proveedor.producto_id", "POST", "/proveedores/{proveedor}/productos",
           lambda a: {"producto_id": a.nuevo("producto")}, ("producto_id",), "producto"),
    *[
        CasoFK(f"orden_compra.{nombre} (crear)", "POST", "/ordenes-compra",
               lambda a: {
                   "codigo": f"OF{a.n():04d}",
                   "proveedor_id": a.ids["proveedor"],
                   "sucursal_id": a.ids["sucursal"],
                   "detalle": [{"variante_id": a.ids["variante"], "cantidad": 1, "costo_unitario": "1.00"}],
               },
               campo, recurso)
        for nombre, campo, recurso in (
            ("proveedor_id", ("proveedor_id",), "proveedor"),
            ("sucursal_id", ("sucursal_id",), "sucursal"),
            ("detalle.variante_id", ("detalle", 0, "variante_id"), "variante"),
        )
    ],
    *[
        CasoFK(f"orden_compra.{nombre} (actualizar)", "PUT",
               lambda a: f"/ordenes-compra/{a.nuevo('orden_compra')}",
               # Otra variante distinta de la que ya tiene la orden: reemplazar el detalle con la
               # MISMA variante falla hoy con un 500 (defecto previo de CU-08, ver el resumen de E05).
               lambda a: {
                   "proveedor_id": a.ids["proveedor"],
                   "sucursal_id": a.ids["sucursal"],
                   "detalle": [{"variante_id": a.nuevo("variante"), "cantidad": 1, "costo_unitario": "1.00"}],
               },
               campo, recurso)
        for nombre, campo, recurso in (
            ("proveedor_id", ("proveedor_id",), "proveedor"),
            ("sucursal_id", ("sucursal_id",), "sucursal"),
            ("detalle.variante_id", ("detalle", 0, "variante_id"), "variante"),
        )
    ],
    *[
        CasoFK(f"recepcion.{nombre}", "POST", "/recepciones",
               lambda a: {
                   "codigo": f"RF{a.n():04d}",
                   "orden_compra_id": _orden_enviada(a),
                   "proveedor_id": a.ids["proveedor"],
                   "sucursal_id": a.ids["sucursal"],
                   "detalle": [{"variante_id": a.ids["variante"], "cantidad": 1, "costo_unitario": "1.00"}],
               },
               campo, recurso)
        for nombre, campo, recurso in (
            ("orden_compra_id", ("orden_compra_id",), "orden_compra"),
            ("proveedor_id", ("proveedor_id",), "proveedor"),
            ("sucursal_id", ("sucursal_id",), "sucursal"),
            ("detalle.variante_id", ("detalle", 0, "variante_id"), "variante"),
        )
    ],
    CasoFK("probador/talla.variante_id", "POST", "/probador/talla",
           lambda a: {"variante_id": a.ids["variante"], "estatura_cm": 175, "peso_kg": 70}, ("variante_id",), "variante", token="cliente"),
    CasoFK("probador/assets.variante_id", "POST", "/probador/assets",
           lambda a: {"variante_id": a.nuevo("variante"), "tipo": "overlay_2d"}, ("variante_id",), "variante", multipart=True),
    CasoFK("probador/generar.variante_id", "POST", "/probador/generar",
           lambda a: {"variante_id": a.ids["variante"]}, ("variante_id",), "variante", token="cliente", multipart=True, espejo=False),
    # comercial
    CasoFK("reserva.sucursal_id", "POST", "/reservas",
           lambda a: {"sucursal_id": a.ids["sucursal"], "fecha_visita": _dia_libre(a), "hora_visita_desde": "10:00:00",
                      "hora_visita_hasta": "11:00:00", "detalle": [{"variante_id": a.ids["variante"], "cantidad": 1}]},
           ("sucursal_id",), "sucursal", token="cliente"),
    CasoFK("reserva.detalle.variante_id", "POST", "/reservas",
           lambda a: {"sucursal_id": a.ids["sucursal"], "fecha_visita": _dia_libre(a), "hora_visita_desde": "10:00:00",
                      "hora_visita_hasta": "11:00:00", "detalle": [{"variante_id": a.ids["variante"], "cantidad": 1}]},
           ("detalle", 0, "variante_id"), "variante", token="cliente"),
    CasoFK("reserva.seleccion.variante_id", "PUT", lambda a: f"/reservas/{_reserva_en_prueba(a)}/seleccion",
           lambda a: {"lineas": [{"variante_id": a.ids["variante"], "seleccionada": True}]}, ("lineas", 0, "variante_id"), "variante"),
    CasoFK("carrito.variante_id", "POST", "/carrito",
           lambda a: {"variante_id": a.nuevo("variante"), "cantidad": 1}, ("variante_id",), "variante", token="cliente"),
    *[
        CasoFK(f"promocion.alcance.{campo}", "POST", "/promociones",
               lambda a, campo=campo, recurso=recurso: _promocion(a, {campo: a.ids[recurso]}),
               ("alcances", 0, campo), recurso)
        for campo, recurso in (("producto_id", "producto"), ("categoria_id", "categoria"), ("temporada_id", "temporada"))
    ],
    CasoFK("venta_presencial.sucursal_id", "POST", "/ventas/presencial", _venta_presencial, ("sucursal_id",), "sucursal"),
    CasoFK("venta_presencial.detalle.variante_id", "POST", "/ventas/presencial", _venta_presencial, ("detalle", 0, "variante_id"), "variante"),
    CasoFK("venta_presencial.reserva_id", "POST", "/ventas/presencial",
           lambda a: _venta_presencial(a, reserva_id=a.ids["reserva"]), ("reserva_id",), "reserva"),
    CasoFK("venta_presencial.cliente_id", "POST", "/ventas/presencial", _venta_presencial, ("cliente_id",), "cliente"),
    CasoFK("venta_digital.sucursal_id", "POST", "/ventas/digital", _carrito_con_prenda, ("sucursal_id",), "sucursal", token="cliente"),
    CasoFK("devolucion.venta_id", "POST", "/devoluciones", _linea_devolucion, ("venta_id",), "venta"),
    CasoFK("devolucion.venta_detalle_id", "POST", "/devoluciones", _linea_devolucion, ("detalle", 0, "venta_detalle_id"), "venta_detalle"),
    # Un cambio de talla o color: el id cruzado se resuelve (404) ANTES de escribir nada. La petición positiva no se
    # ejecuta aquí (el cambio válido necesita otra talla del mismo producto: lo prueban tests/comercial/test_cambio_talla.py).
    CasoFK("devolucion.variante_nueva_id", "POST", "/devoluciones",
           lambda a: {**_linea_devolucion(a), "detalle": [{**_linea_devolucion(a)["detalle"][0], "variante_nueva_id": a.ids["variante"]}]},
           ("detalle", 0, "variante_nueva_id"), "variante", espejo=False),
    # Solicitud de cambio del cliente (Etapa 2): los tres ids del cuerpo se resuelven (404) ANTES de escribir nada.
    # Una petición positiva válida necesita otra talla del mismo producto: la prueba tests/comercial/test_solicitud_cambio.py.
    CasoFK("solicitud_cambio.venta_id", "POST", "/solicitudes-cambio", _solicitud_cambio, ("venta_id",), "venta",
           token="cliente", espejo=False),
    CasoFK("solicitud_cambio.venta_detalle_id", "POST", "/solicitudes-cambio", _solicitud_cambio,
           ("detalle", 0, "venta_detalle_id"), "venta_detalle", token="cliente", espejo=False),
    CasoFK("solicitud_cambio.variante_nueva_id", "POST", "/solicitudes-cambio", _solicitud_cambio,
           ("detalle", 0, "variante_nueva_id"), "variante", token="cliente", espejo=False),
    # Pedido sin conexión: la sucursal y cada prenda se resuelven (404) ANTES de reservar la operación. La petición
    # positiva cobraría con PayPal: la prueba tests/comercial/test_pedido_diferido.py la hace con PayPal simulado.
    CasoFK("pedido_diferido.sucursal_id", "POST", "/pedidos-diferidos", _pedido_diferido, ("sucursal_id",), "sucursal",
           token="cliente", espejo=False),
    CasoFK("pedido_diferido.lineas.variante_id", "POST", "/pedidos-diferidos", _pedido_diferido,
           ("lineas", 0, "variante_id"), "variante", token="cliente", espejo=False),
    CasoFK("pago_caja.venta_id", "POST", "/pagos/caja",
           lambda a: {"venta_id": a.nuevo("venta_pendiente"), "metodo_pago": "efectivo", "monto_recibido": "99999"}, ("venta_id",), "venta"),
    CasoFK("pago_iniciar.venta_id", "POST", "/pagos/iniciar",
           lambda a: {"venta_id": a.ids["venta_pendiente"], "metodo_pago": "libelula"}, ("venta_id",), "venta",
           token="cliente", espejo=False),
    CasoFK("zona_envio.ciudad_id", "POST", "/zonas-envio",
           lambda a: {"ciudad_id": a.ids["ciudad"], "nombre": f"Zona FK {a.n()}", "tarifa_base": "3.00"}, ("ciudad_id",), "ciudad"),
    CasoFK("direccion.zona_envio_id (crear)", "POST", "/clientes/direcciones",
           lambda a: {"zona_envio_id": a.ids["zona_envio"], "direccion": "Calle FK"}, ("zona_envio_id",), "zona_envio", token="cliente"),
    CasoFK("direccion.zona_envio_id (actualizar)", "PUT", "/clientes/direcciones/{direccion}",
           lambda a: {"zona_envio_id": a.ids["zona_envio"]}, ("zona_envio_id",), "zona_envio", token="cliente"),
    CasoFK("cotizar.direccion_id", "POST", "/envios/cotizar",
           lambda a: {"direccion_id": a.ids["direccion"], "cantidad_prendas": 1}, ("direccion_id",), "direccion", token="cliente"),
    CasoFK("envio.venta_id", "POST", "/envios",
           lambda a: {"venta_id": a.nuevo("venta_pendiente"), "direccion_id": a.ids["direccion"]}, ("venta_id",), "venta"),
    CasoFK("envio.direccion_id", "POST", "/envios",
           lambda a: {"venta_id": a.nuevo("venta_pendiente"), "direccion_id": a.ids["direccion"]}, ("direccion_id",), "direccion"),
    # inteligencia
    CasoFK("evento.producto_id", "POST", "/ia/eventos",
           lambda a: {"tipo_evento": "vista", "producto_id": a.ids["producto"]}, ("producto_id",), "producto", token="cliente"),
    CasoFK("evento.variante_id", "POST", "/ia/eventos",
           lambda a: {"tipo_evento": "vista", "variante_id": a.ids["variante"]}, ("variante_id",), "variante", token="cliente"),
]
