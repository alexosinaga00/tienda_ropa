"""Seed de los 5 roles (según docs/fashionstore_esquema.sql) y sus permisos.

El SQL solo trae los nombres de los roles; los permisos no existen todavía
en ningún lado, así que se definen acá, uno por dominio de negocio (el prefijo del permiso), y se
asignan por rol según lo que cada uno necesita operar. Idempotente: correrlo
más de una vez no duplica filas.

Uso:
    .venv/Scripts/python -m scripts.seed_seguridad
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.plataforma.models import Permiso, Rol

ROLES: list[tuple[str, str]] = [
    ("superadministrador", "Administrador de la plataforma, sin empresa"),
    ("administrador", "Acceso total al sistema"),
    ("encargado_sucursal", "Gestiona reservas e inventario de su sucursal"),
    ("cajero", "Registra ventas presenciales y cobros"),
    ("proveedor", "Registra información de sus productos"),
    ("cliente", "Compra, reserva y usa el probador virtual"),
]

PERMISOS: list[tuple[str, str, str]] = [
    # codigo, modulo, descripcion
    ("usuarios.gestionar", "seguridad", "Crear, editar y desactivar usuarios"),
    ("roles.gestionar", "seguridad", "Crear, editar roles y asignar permisos"),
    ("organizacion.gestionar", "organizacion", "Gestionar ciudades, sucursales, horarios y empleados"),
    ("catalogo.gestionar", "catalogo", "Crear y editar productos, variantes e imágenes"),
    ("catalogo.ver", "catalogo", "Consultar el catálogo"),
    ("abastecimiento.gestionar", "abastecimiento", "Gestionar proveedores, órdenes de compra y recepciones"),
    ("inventario.gestionar", "inventario", "Registrar movimientos, transferencias y ajustes de inventario"),
    ("inventario.ver", "inventario", "Consultar inventario y kardex"),
    ("reservas.gestionar_sucursal", "reservas", "Preparar, confirmar y atender reservas de la sucursal"),
    ("reservas.crear", "reservas", "Crear y cancelar reservas propias"),
    ("ventas.presencial", "ventas", "Registrar ventas en caja"),
    ("ventas.digital", "ventas", "Comprar desde la app o la web"),
    ("ventas.gestionar_sucursal", "ventas", "Ver las ventas de la sucursal y procesar devoluciones"),
    ("ventas.gestionar", "ventas", "Crear y editar promociones"),
    ("pagos.gestionar", "pagos", "Cobrar en caja y anular pagos"),
    ("entregas.gestionar", "entregas", "Gestionar zonas de envío y el estado de los envíos"),
    ("reportes.ver", "reportes", "Consultar reportes y el dashboard"),
    ("probador.usar", "probador", "Usar el vestidor virtual"),
    ("probador.gestionar", "probador", "Subir y validar assets del probador"),
    ("plataforma.gestionar", "plataforma", "Gestionar empresas, planes y suscripciones de la plataforma"),
    ("empresa.gestionar", "plataforma", "Gestionar la empresa propia y su suscripción"),
    ("bitacora.ver", "bitacora", "Consultar la bitácora de auditoría de la empresa"),
    ("sincronizacion.operar", "sincronizacion", "Enviar operaciones hechas sin conexión y consultar las propias"),
    ("sincronizacion.supervisar", "sincronizacion", "Ver las operaciones sin conexión de la empresa o de la sucursal"),
    ("sincronizacion.resolver", "sincronizacion", "Forzar o rechazar una operación sin conexión en conflicto"),
    ("copias.gestionar", "copias", "Crear y descargar la copia de seguridad de la empresa"),
    ("caja.supervisar", "caja", "Ver los cierres de caja, cerrar el turno de otra persona y completar un conteo"),
]

# Permisos que NO recibe el administrador de una empresa: son del
# superadministrador (si no, cada administrador sería superadministrador).
PERMISOS_SOLO_PLATAFORMA = ["plataforma.gestionar"]

PERMISOS_POR_ROL: dict[str, list[str]] = {
    # El superadministrador no opera negocio: solo la plataforma y los roles.
    "superadministrador": ["plataforma.gestionar", "roles.gestionar"],
    "administrador": [codigo for codigo, _, _ in PERMISOS if codigo not in PERMISOS_SOLO_PLATAFORMA],
    "encargado_sucursal": [
        "catalogo.ver",
        "inventario.gestionar",
        "inventario.ver",
        "reservas.gestionar_sucursal",
        "ventas.gestionar_sucursal",
        "entregas.gestionar",
        "reportes.ver",
        "sincronizacion.operar",
        "sincronizacion.supervisar",
        "sincronizacion.resolver",
        "caja.supervisar",
    ],
    "cajero": [
        "catalogo.ver",
        "inventario.ver",
        "ventas.presencial",
        "ventas.gestionar_sucursal",
        "pagos.gestionar",
        # Para el atajo "cargar reserva atendida" de la caja (P5.4): el
        # cajero necesita ver las reservas de su sucursal para convertirlas
        # en venta, no solo el encargado del depósito.
        "reservas.gestionar_sucursal",
        "sincronizacion.operar",
    ],
    # Sin abastecimiento.gestionar: ese permiso protege TODA la sección de Abastecimiento
    # (proveedores ajenos, órdenes de compra y recepciones, que suben stock
    # y fijan el costo promedio en cualquier sucursal) y no hay endpoints
    # acotados al proveedor dueño de la sesión. Es un tercero externo: solo
    # consulta el catálogo.
    "proveedor": [
        "catalogo.ver",
    ],
    "cliente": [
        "catalogo.ver",
        "reservas.crear",
        "ventas.digital",
        "probador.usar",
    ],
}


def seed(db: Session) -> None:
    roles_por_nombre: dict[str, Rol] = {}
    for nombre, descripcion in ROLES:
        rol = db.query(Rol).filter(Rol.nombre == nombre).one_or_none()
        if rol is None:
            rol = Rol(nombre=nombre, descripcion=descripcion)
            db.add(rol)
            db.flush()
        roles_por_nombre[nombre] = rol

    permisos_por_codigo: dict[str, Permiso] = {}
    for codigo, modulo, descripcion in PERMISOS:
        permiso = db.query(Permiso).filter(Permiso.codigo == codigo).one_or_none()
        if permiso is None:
            permiso = Permiso(codigo=codigo, modulo=modulo, descripcion=descripcion)
            db.add(permiso)
            db.flush()
        permisos_por_codigo[codigo] = permiso

    for nombre_rol, codigos in PERMISOS_POR_ROL.items():
        rol = roles_por_nombre[nombre_rol]
        rol.permisos = [permisos_por_codigo[c] for c in codigos]

    db.commit()


if __name__ == "__main__":
    session = SessionLocal()
    try:
        seed(session)
        print("Seed de seguridad aplicado.")
    finally:
        session.close()
