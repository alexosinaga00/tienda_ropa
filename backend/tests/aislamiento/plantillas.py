"""E05, 4.3: las tablas de apoyo de la matriz.

PARAMETROS  nombre de parámetro de ruta -> recurso del universo (los roles son globales y
            quedan fuera).
CUERPOS     (método, ruta) -> función(universo) que arma un cuerpo válido para ESA empresa.
TOKEN       qué token usa la prueba para cada ruta (por defecto el administrador).

Para dar de alta una ruta nueva en la matriz hay que declarar aquí su cuerpo de ejemplo
(si lo necesita); sin él, la prueba la manda sin cuerpo y falla con un 422 que lo dice.
"""

import datetime as dt

from .universo import Universo

# --- parámetros de ruta -> clave de `Universo.ids` ---------------------------------------

EXCLUIDOS = {"rol_id", "codigo", "pasarela", "id_transaccion"}

PARAMETROS = {
    "variante_id": "variante",
    "categoria_id": "categoria",
    "ciudad_id": "ciudad",
    "direccion_id": "direccion",
    "coleccion_id": "coleccion",
    "color_id": "color",
    "empleado_id": "empleado",
    "imagen_id": "imagen",
    "material_id": "material",
    "orden_id": "orden_compra",
    "producto_id": "producto",
    "medida_id": "medida",
    "promocion_id": "promocion",
    "proveedor_id": "proveedor",
    "reserva_id": "reserva",
    "sucursal_id": "sucursal",
    "horario_id": "horario",
    "talla_id": "talla",
    "temporada_id": "temporada",
    "transferencia_id": "transferencia",
    "usuario_id": "usuario",
    "zona_id": "zona_envio",
    "envio_id": "envio",
    "venta_id": "venta",
    "notificacion_id": "notificacion",
    "bitacora_id": "bitacora",
    "operacion_id": "operacion_sync",
    "pago_id": "pago",
    "recepcion_id": "recepcion",
    "activo_id": "activo_probador",
    "generacion_id": "generacion",
    "stock_id": "stock",
    "copia_id": "copia_seguridad",
    "solicitud_id": "solicitud_cambio",
    "reembolso_id": "reembolso",
    "turno_id": "caja_turno",
}

# --- token con el que A pide cada ruta ----------------------------------------------------

_BASE = "/api/v1"

TOKEN_CLIENTE = {
    ("PUT", f"{_BASE}/clientes/direcciones/{{direccion_id}}"),
    ("DELETE", f"{_BASE}/clientes/direcciones/{{direccion_id}}"),
    ("POST", f"{_BASE}/pagos/venta/{{venta_id}}/cancelar"),
    ("GET", f"{_BASE}/reservas/{{reserva_id}}"),
    ("DELETE", f"{_BASE}/reservas/{{reserva_id}}"),
    ("GET", f"{_BASE}/probador/generar/{{generacion_id}}"),
    ("GET", f"{_BASE}/probador/variante/{{variante_id}}/assets"),
    ("GET", f"{_BASE}/pagos/{{pago_id}}/estado"),
    ("GET", f"{_BASE}/ventas/{{venta_id}}/comprobante"),
    ("GET", f"{_BASE}/ventas/{{venta_id}}/plazo-cambio"),
    ("GET", f"{_BASE}/reservas/mis-reservas"),
    ("GET", f"{_BASE}/clientes/direcciones"),
    # Solo quien pidió la solicitud puede cancelarla.
    ("POST", f"{_BASE}/solicitudes-cambio/{{solicitud_id}}/cancelar"),
}


def token_de_ruta(metodo: str, ruta: str) -> str:
    return "cliente" if (metodo, ruta) in TOKEN_CLIENTE else "admin"


# --- cuerpos de ejemplo ---------------------------------------------------------------------


def _n(u: Universo) -> int:
    return u.n()


CUERPOS = {
    ("PUT", f"{_BASE}/categorias/{{categoria_id}}"): lambda u: {"descripcion": f"cambiada {_n(u)}"},
    ("PUT", f"{_BASE}/ciudades/{{ciudad_id}}"): lambda u: {"departamento": f"Dpto {_n(u)}"},
    ("PUT", f"{_BASE}/clientes/direcciones/{{direccion_id}}"): lambda u: {"referencia": f"ref {_n(u)}"},
    ("PUT", f"{_BASE}/colecciones/{{coleccion_id}}"): lambda u: {"descripcion": f"cambiada {_n(u)}"},
    ("PUT", f"{_BASE}/colores/{{color_id}}"): lambda u: {"codigo_hex": "#112233"},
    ("PUT", f"{_BASE}/empleados/{{empleado_id}}"): lambda u: {"cargo": f"Cargo {_n(u)}"},
    ("PUT", f"{_BASE}/envios/{{envio_id}}/estado"): lambda u: {"estado": "en_ruta", "repartidor": f"Rep {_n(u)}"},
    ("PUT", f"{_BASE}/inventario/stock/{{stock_id}}/limites"): lambda u: {"stock_minimo": 2, "stock_maximo": 500},
    ("PUT", f"{_BASE}/materiales/{{material_id}}"): lambda u: {"descripcion": f"cambiada {_n(u)}"},
    ("PUT", f"{_BASE}/ordenes-compra/{{orden_id}}"): lambda u: {"fecha_esperada": (dt.date.today() + dt.timedelta(days=9)).isoformat()},
    ("PUT", f"{_BASE}/productos/{{producto_id}}"): lambda u: {"descripcion": f"cambiada {_n(u)}"},
    ("POST", f"{_BASE}/productos/{{producto_id}}/medidas"): lambda u: {"talla_id": u.nuevo("talla"), "pecho_min_cm": "85"},
    ("PUT", f"{_BASE}/productos/{{producto_id}}/medidas/{{medida_id}}"): lambda u: {"pecho_min_cm": "88"},
    ("POST", f"{_BASE}/productos/{{producto_id}}/variantes"): lambda u: {
        "tallas_ids": [u.nuevo("talla")],
        "colores_ids": [u.nuevo("color")],
    },
    ("PUT", f"{_BASE}/promociones/{{promocion_id}}"): lambda u: {"nombre": f"Promo {_n(u)}"},
    ("POST", f"{_BASE}/sincronizacion/operaciones/{{operacion_id}}/resolver"): lambda u: {"accion": "rechazar", "motivo": "prueba"},
    ("POST", f"{_BASE}/solicitudes-cambio/{{solicitud_id}}/rechazar"): lambda u: {"motivo": "prueba de aislamiento"},
    ("POST", f"{_BASE}/caja/turnos/{{turno_id}}/cerrar"): lambda u: {"efectivo_contado": "10.00"},
    ("POST", f"{_BASE}/caja/turnos/{{turno_id}}/completar-conteo"): lambda u: {"efectivo_contado": "10.00", "observacion": "prueba de aislamiento"},
    ("PUT", f"{_BASE}/proveedores/{{proveedor_id}}"): lambda u: {"contacto": f"Contacto {_n(u)}"},
    ("POST", f"{_BASE}/proveedores/{{proveedor_id}}/productos"): lambda u: {"producto_id": u.nuevo("producto")},
    ("PUT", f"{_BASE}/reservas/{{reserva_id}}/seleccion"): lambda u: {"lineas": [{"variante_id": u.ids["variante"], "seleccionada": True}]},
    ("PUT", f"{_BASE}/sucursales/{{sucursal_id}}"): lambda u: {"telefono": f"7{_n(u):07d}"},
    ("POST", f"{_BASE}/sucursales/{{sucursal_id}}/horarios"): lambda u: {
        "dia_semana": 1,
        "hora_apertura": "05:00:00",
        "hora_cierre": "06:00:00",
    },
    ("PUT", f"{_BASE}/sucursales/{{sucursal_id}}/horarios/{{horario_id}}"): lambda u: {"hora_cierre": "21:00:00"},
    ("PUT", f"{_BASE}/tallas/{{talla_id}}"): lambda u: {"descripcion": f"cambiada {_n(u)}"},
    ("PUT", f"{_BASE}/temporadas/{{temporada_id}}"): lambda u: {"nombre": f"Temporada {_n(u)}"},
    ("PUT", f"{_BASE}/usuarios/{{usuario_id}}"): lambda u: {"telefono": f"6{_n(u):07d}"},
    ("PUT", f"{_BASE}/usuarios/{{usuario_id}}/roles"): lambda u: {"nombres_rol": ["cajero"]},
    ("PUT", f"{_BASE}/variantes/{{variante_id}}"): lambda u: {"codigo_barras": f"CB{_n(u):08d}"},
    ("PUT", f"{_BASE}/zonas-envio/{{zona_id}}"): lambda u: {"tarifa_base": "11.00"},
}

# Rutas multipart: el archivo se manda aparte (nombre del campo, contenido, tipo).
ARCHIVOS = {
    ("POST", f"{_BASE}/productos/{{producto_id}}/imagenes"): {
        "archivo": ("prenda.png", b"\x89PNG\r\n\x1a\n" + b"0" * 32, "image/png")
    },
}

# --- prueba espejo (O5) ----------------------------------------------------------------------
# Las rutas que borran o cambian de estado lo que tocan usan, para la prueba positiva, una
# instancia DESECHABLE (`Universo.nuevo`) en vez de la del universo. Recurso -> clave de `nuevo`.
NUEVO_PARA_ESPEJO = {
    "categoria": "categoria",
    "ciudad": "ciudad",
    "coleccion": "coleccion",
    "color": "color",
    "direccion": "direccion",
    "empleado": "empleado",
    "imagen": "imagen",
    "material": "material",
    "medida": "medida",
    "notificacion": "notificacion",
    "orden_compra": "orden_compra",
    "pago": "pago",
    "producto": "producto",
    "promocion": "promocion",
    "proveedor": "proveedor",
    "solicitud_cambio": "solicitud_cambio",
    "reserva": "reserva",
    "sucursal": "sucursal",
    "talla": "talla",
    "temporada": "temporada",
    "transferencia": "transferencia",
    "usuario": "usuario",
    "variante": "variante",
    "venta": "venta_pendiente",
    "zona_envio": "zona_envio",
    "activo_probador": "activo_probador",
}

def _horario_en_destino(a: Universo) -> dict:
    destino = a.ids["sucursal_destino"]
    return {"sucursal_id": destino, "horario_id": a.nuevo("horario", sucursal_id=destino)}


def _proveedor_con_producto(a: Universo) -> dict:
    from .universo import crear

    proveedor = a.nuevo("proveedor")
    crear(a.client, f"/proveedores/{proveedor}/productos", {"producto_id": a.ids["producto"]}, a.admin)
    return {"proveedor_id": proveedor, "producto_id": a.ids["producto"]}


# Rutas cuyos ids propios no salen de la regla general: función(universo) -> {parámetro: id}.
VALORES_ESPEJO = {
    ("GET", f"{_BASE}/envios/venta/{{venta_id}}"): lambda a: {"venta_id": a.ids["venta_con_envio"]},
    ("PUT", f"{_BASE}/sucursales/{{sucursal_id}}/horarios/{{horario_id}}"): _horario_en_destino,
    ("DELETE", f"{_BASE}/sucursales/{{sucursal_id}}/horarios/{{horario_id}}"): _horario_en_destino,
    ("DELETE", f"{_BASE}/proveedores/{{proveedor_id}}/productos/{{producto_id}}"): _proveedor_con_producto,
}

# Rutas cuyo espejo no se ejecuta (necesitarían un servicio externo); la prueba cruzada sí corre.
SIN_ESPEJO: dict = {}

# Estados con los que se acepta el espejo: la ruta ENCONTRÓ el recurso (2xx) o aplicó una regla
# de negocio sobre él (400 y 409). Un 404, 422 o 5xx indican una prueba mal armada o una fuga.
ESPEJO_ACEPTADO = tuple(range(200, 300)) + (400, 409)
