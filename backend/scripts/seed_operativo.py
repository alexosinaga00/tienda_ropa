"""Seed de la parte operativa: sucursales con horarios, staff (admin,
encargados, cajeros, proveedor) con su fila en `empleado`, proveedores,
producto_proveedor y stock inicial vía orden de compra + recepción.

Todas las escrituras pasan por los services de cada paquete (no INSERT a
mano), así se aplican las mismas validaciones que en la app y el stock
queda respaldado por movimientos de kardex con costo promedio. Las lecturas
para decidir si algo ya existe consultan los modelos directo, igual que el
resto de los seeds.

Idempotente y reanudable: cada entidad tiene una clave natural (código de
sucursal, email, NIT, código de OC/recepción) y se omite si ya existe. Si
una corrida se corta entre la OC y la recepción, la siguiente retoma desde
donde quedó.

Requiere que ya estén los seeds base (ver scripts.seed_todo) y productos
con variantes (scripts.seed_prendas_probador).

Por defecto NO escribe nada (dry-run). Para escribir hace falta --ejecutar.

Uso (desde backend/):
    python -m scripts.seed_operativo
    python -m scripts.seed_operativo --ejecutar

Variables de entorno: DATABASE_URL, JWT_SECRET_KEY (la exige Settings) y,
con --ejecutar, SEED_PASSWORD_INICIAL (contraseña inicial del staff creado,
mínimo 8 caracteres).
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from collections import defaultdict
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

CIUDAD_NOMBRE = "Santa Cruz de la Sierra"
CIUDAD_DEPARTAMENTO = "Santa Cruz"
DOMINIO = "fashionstore.bo"


@dataclass(frozen=True)
class SucursalSeed:
    codigo: str
    nombre: str
    direccion: str
    telefono: str
    latitud: Decimal
    longitud: Decimal
    es_deposito: bool
    # Unidades a recibir por talla; el resto de tallas usa "otras".
    cantidades: dict[str, int]
    stock_minimo: int
    stock_maximo: int


SUCURSALES: list[SucursalSeed] = [
    SucursalSeed(
        "SC-CENTRO", "FashionStore Centro", "Calle 24 de Septiembre 145, Casco Viejo", "33345678",
        Decimal("-17.7833000"), Decimal("-63.1821000"), False,
        {"L": 10, "XL": 8, "otras": 6}, 3, 30,
    ),
    SucursalSeed(
        "SC-EQUIPETROL", "FashionStore Equipetrol", "Av. San Martin 820, Equipetrol", "33398765",
        Decimal("-17.7625000"), Decimal("-63.1960000"), False,
        {"L": 10, "XL": 8, "otras": 6}, 3, 30,
    ),
    SucursalSeed(
        "SC-DEPOSITO", "Deposito Central", "Parque Industrial, Mz. 12", "33321000",
        Decimal("-17.7300000"), Decimal("-63.1500000"), True,
        {"L": 20, "XL": 15, "otras": 12}, 5, 60,
    ),
]

# dia_semana ISO (1=lunes ... 7=domingo), igual que reservas.service.
HORARIO_TIENDA: dict[int, tuple[dt.time, dt.time]] = {
    **{dia: (dt.time(9, 0), dt.time(21, 0)) for dia in range(1, 7)},
    7: (dt.time(10, 0), dt.time(14, 0)),
}


@dataclass(frozen=True)
class StaffSeed:
    email: str
    nombre: str
    apellido: str
    telefono: str
    rol: str
    # None = no es empleado (el usuario proveedor). "" = empleado sin sucursal.
    sucursal_codigo: str | None
    cargo: str | None
    ci: str | None


STAFF: list[StaffSeed] = [
    StaffSeed(f"admin@{DOMINIO}", "Administrador", "General", "70000001", "administrador", "", "Administrador", "9000001"),
    StaffSeed(f"encargado.centro@{DOMINIO}", "Carla", "Rojas", "70000002", "encargado_sucursal", "SC-CENTRO", "Encargada de sucursal", "9000002"),
    StaffSeed(f"cajero.centro@{DOMINIO}", "Diego", "Suarez", "70000003", "cajero", "SC-CENTRO", "Cajero", "9000003"),
    StaffSeed(f"encargado.equipetrol@{DOMINIO}", "Mariana", "Justiniano", "70000004", "encargado_sucursal", "SC-EQUIPETROL", "Encargada de sucursal", "9000004"),
    StaffSeed(f"cajero.equipetrol@{DOMINIO}", "Luis", "Vaca", "70000005", "cajero", "SC-EQUIPETROL", "Cajero", "9000005"),
    StaffSeed(f"proveedor.andina@{DOMINIO}", "Jorge", "Mendoza", "70000006", "proveedor", None, None, None),
]


@dataclass(frozen=True)
class ProveedorSeed:
    clave: str  # sufijo corto para los códigos de OC/recepción
    nombre: str
    nit: str
    contacto: str
    telefono: str
    email: str
    direccion: str
    usuario_email: str | None
    dias_entrega: int


PROVEEDORES: list[ProveedorSeed] = [
    ProveedorSeed("AND", "Textiles Andina SRL", "1020304011", "Jorge Mendoza", "33311111",
                  "ventas@textilesandina.bo", "Av. Banzer 3er anillo", f"proveedor.andina@{DOMINIO}", 7),
    ProveedorSeed("ORI", "Confecciones del Oriente SA", "1020304022", "Patricia Ribera", "33322222",
                  "pedidos@confeccionesoriente.bo", "Av. Cristo Redentor 4to anillo", None, 15),
    ProveedorSeed("NOR", "Importadora Norte Ltda", "1020304033", "Ramiro Salvatierra", "33333333",
                  "compras@importadoranorte.bo", "Av. Alemana 5to anillo", None, 10),
]

PORCENTAJE_COSTO = Decimal("0.45")
_DOS_DECIMALES = Decimal("0.01")


def _proveedor_para(categoria: str | None, nombre_producto: str) -> str:
    """Chamarras -> Oriente; polos y camisetas -> Norte; resto -> Andina."""
    if categoria == "Chamarras":
        return "ORI"
    primera = nombre_producto.split()[0].lower() if nombre_producto else ""
    if primera in {"polo", "camiseta"}:
        return "NOR"
    return "AND"


class Resumen:
    def __init__(self) -> None:
        self.creados: dict[str, int] = defaultdict(int)
        self.existentes: dict[str, int] = defaultdict(int)

    def creado(self, entidad: str, n: int = 1) -> None:
        self.creados[entidad] += n

    def existente(self, entidad: str, n: int = 1) -> None:
        self.existentes[entidad] += n

    def imprimir(self, ejecutar: bool) -> None:
        verbo = "creados" if ejecutar else "a crear"
        entidades = list(dict.fromkeys([*self.creados, *self.existentes]))
        print(f"\n{'entidad':22} {verbo:>10} {'ya existían':>12}")
        for entidad in entidades:
            print(f"{entidad:22} {self.creados.get(entidad, 0):>10} {self.existentes.get(entidad, 0):>12}")


# ---- Pasos ----------------------------------------------------------------------


def verificar_precondiciones(db: Session) -> int:
    from app.catalogo.models import Producto, ProductoVariante
    from app.inventario.models import TipoMovimiento
    from app.organizacion.models import Ciudad
    from app.seguridad.models import Rol

    errores: list[str] = []
    ciudad = db.scalar(
        select(Ciudad).where(Ciudad.nombre == CIUDAD_NOMBRE, Ciudad.departamento == CIUDAD_DEPARTAMENTO)
    )
    if ciudad is None or not ciudad.activo:
        errores.append(f"Falta la ciudad '{CIUDAD_NOMBRE}' (correr scripts.seed_entregas)")

    roles = set(db.scalars(select(Rol.nombre).where(Rol.activo.is_(True))))
    faltan_roles = {s.rol for s in STAFF} - roles
    if faltan_roles:
        errores.append(f"Faltan los roles {sorted(faltan_roles)} (correr scripts.seed_seguridad)")

    if db.scalar(select(TipoMovimiento).where(TipoMovimiento.codigo == "recepcion")) is None:
        errores.append("Falta el tipo de movimiento 'recepcion' (correr scripts.seed_inventario)")

    hay_variantes = db.scalar(
        select(ProductoVariante.id)
        .join(Producto, Producto.id == ProductoVariante.producto_id)
        .where(Producto.activo.is_(True), ProductoVariante.activo.is_(True))
        .limit(1)
    )
    if hay_variantes is None:
        errores.append("No hay productos activos con variantes (correr scripts.seed_prendas_probador)")

    if errores:
        sys.exit("Precondiciones no cumplidas:\n  - " + "\n  - ".join(errores))
    return ciudad.id


def seed_sucursales(db: Session, ciudad_id: int, ejecutar: bool, resumen: Resumen) -> dict[str, int | None]:
    from app.organizacion.casos_uso.cu05_gestionar_sucursales import GestionarSucursales
    from app.organizacion.models import Sucursal
    from app.organizacion.politicas import obtener_horario_dia
    from app.organizacion.schemas import HorarioCrear, SucursalCrear

    cu_sucursales = GestionarSucursales()
    ids: dict[str, int | None] = {}
    for s in SUCURSALES:
        sucursal = db.scalar(select(Sucursal).where(Sucursal.codigo == s.codigo))
        if sucursal is not None and not sucursal.activo:
            sys.exit(f"La sucursal {s.codigo} existe pero está inactiva: reactivarla a mano antes de seguir")
        if sucursal is None:
            resumen.creado("sucursal")
            if ejecutar:
                sucursal = cu_sucursales.crear(
                    db,
                    SucursalCrear(
                        ciudad_id=ciudad_id, codigo=s.codigo, nombre=s.nombre, direccion=s.direccion,
                        telefono=s.telefono, latitud=s.latitud, longitud=s.longitud, es_deposito=s.es_deposito,
                    ),
                )
                print(f"  sucursal {s.codigo} creada id={sucursal.id}")
        else:
            resumen.existente("sucursal")
        ids[s.codigo] = sucursal.id if sucursal is not None else None

        if s.es_deposito:
            continue
        for dia, (apertura, cierre) in HORARIO_TIENDA.items():
            existe = sucursal is not None and obtener_horario_dia(db, sucursal.id, dia)
            if existe:
                resumen.existente("horario_sucursal")
                continue
            resumen.creado("horario_sucursal")
            if ejecutar:
                cu_sucursales.crear_horario(
                    db, sucursal.id, HorarioCrear(dia_semana=dia, hora_apertura=apertura, hora_cierre=cierre)
                )
    return ids


def seed_staff(
    db: Session, sucursales: dict[str, int | None], password: str | None, ejecutar: bool, resumen: Resumen
) -> tuple[dict[str, int | None], dict[str, int | None]]:
    """Devuelve (usuario_id por email, empleado_id por email)."""
    from app.organizacion.casos_uso.cu06_gestionar_empleados import GestionarEmpleados
    from app.organizacion.politicas import obtener_empleado_por_usuario
    from app.organizacion.schemas import EmpleadoCrear
    from app.seguridad.casos_uso.cu03_gestionar_usuarios_roles_permisos import GestionarUsuarios
    from app.seguridad.models import Usuario
    from app.seguridad.schemas import UsuarioCrear

    cu_empleados = GestionarEmpleados()
    cu_usuarios = GestionarUsuarios()
    usuarios: dict[str, int | None] = {}
    empleados: dict[str, int | None] = {}
    for s in STAFF:
        usuario = db.scalar(select(Usuario).where(Usuario.email == s.email))
        if usuario is None:
            resumen.creado("usuario")
            if ejecutar:
                usuario = cu_usuarios.crear(
                    db,
                    UsuarioCrear(nombre=s.nombre, apellido=s.apellido, email=s.email, telefono=s.telefono, password=password),
                )
                print(f"  usuario {s.email} creado id={usuario.id}")
        else:
            resumen.existente("usuario")

        # Solo agrega el rol del seed: no le quita a nadie los roles que ya tenga.
        roles_actuales = {r.nombre for r in usuario.roles} if usuario is not None else set()
        if s.rol not in roles_actuales:
            resumen.creado("usuario_rol")
            if ejecutar:
                cu_usuarios.asignar_roles(db, usuario.id, [*roles_actuales, s.rol])
        else:
            resumen.existente("usuario_rol")
        usuarios[s.email] = usuario.id if usuario is not None else None

        if s.sucursal_codigo is None:
            continue
        empleado = obtener_empleado_por_usuario(db, usuario.id) if usuario is not None else None
        if empleado is None:
            resumen.creado("empleado")
            if ejecutar:
                empleado = cu_empleados.crear(
                    db,
                    EmpleadoCrear(
                        usuario_id=usuario.id,
                        sucursal_id=sucursales[s.sucursal_codigo] if s.sucursal_codigo else None,
                        ci=s.ci,
                        cargo=s.cargo,
                        fecha_ingreso=dt.date.today(),
                    ),
                )
        else:
            resumen.existente("empleado")
        empleados[s.email] = empleado.id if empleado is not None else None
    return usuarios, empleados


def seed_proveedores(
    db: Session, usuarios: dict[str, int | None], ejecutar: bool, resumen: Resumen
) -> dict[str, int | None]:
    from app.abastecimiento.casos_uso.cu11_gestionar_proveedores import GestionarProveedores
    from app.abastecimiento.models import Proveedor
    from app.abastecimiento.schemas import ProveedorCrear

    cu_proveedores = GestionarProveedores()
    ids: dict[str, int | None] = {}
    for p in PROVEEDORES:
        proveedor = db.scalar(select(Proveedor).where(Proveedor.nit == p.nit))
        if proveedor is not None and not proveedor.activo:
            sys.exit(f"El proveedor NIT {p.nit} existe pero está inactivo: reactivarlo a mano antes de seguir")
        if proveedor is None:
            resumen.creado("proveedor")
            if ejecutar:
                proveedor = cu_proveedores.crear(
                    db,
                    ProveedorCrear(
                        nombre=p.nombre, nit=p.nit, contacto=p.contacto, telefono=p.telefono, email=p.email,
                        direccion=p.direccion, usuario_id=usuarios.get(p.usuario_email) if p.usuario_email else None,
                    ),
                )
                print(f"  proveedor {p.nombre} creado id={proveedor.id}")
        else:
            resumen.existente("proveedor")
        ids[p.clave] = proveedor.id if proveedor is not None else None
    return ids


@dataclass
class LineaCompra:
    producto_id: int
    variante_id: int
    talla: str
    costo: Decimal


def planificar_compras(db: Session) -> dict[str, list[LineaCompra]]:
    """Variantes activas agrupadas por clave de proveedor."""
    from app.catalogo.models import Categoria, Producto, ProductoVariante, Talla

    filas = db.execute(
        select(Producto, ProductoVariante, Talla.codigo, Categoria.nombre)
        .join(ProductoVariante, ProductoVariante.producto_id == Producto.id)
        .join(Talla, Talla.id == ProductoVariante.talla_id)
        .outerjoin(Categoria, Categoria.id == Producto.categoria_id)
        .where(Producto.activo.is_(True), ProductoVariante.activo.is_(True))
        .order_by(Producto.id, ProductoVariante.id)
    ).all()

    por_proveedor: dict[str, list[LineaCompra]] = defaultdict(list)
    for producto, variante, talla, categoria in filas:
        precio = variante.precio if variante.precio is not None else producto.precio_base
        costo = (precio * PORCENTAJE_COSTO).quantize(_DOS_DECIMALES, rounding=ROUND_HALF_UP)
        clave = _proveedor_para(categoria, producto.nombre)
        por_proveedor[clave].append(LineaCompra(producto.id, variante.id, talla, costo))
    return por_proveedor


def seed_producto_proveedor(
    db: Session, proveedores: dict[str, int | None], compras: dict[str, list[LineaCompra]], ejecutar: bool, resumen: Resumen
) -> None:
    from app.abastecimiento.casos_uso.cu11_gestionar_proveedores import GestionarProveedores

    cu_proveedores = GestionarProveedores()
    dias_por_clave = {p.clave: p.dias_entrega for p in PROVEEDORES}
    for clave, lineas in compras.items():
        proveedor_id = proveedores[clave]
        ya_asociados = (
            {pp.producto_id for pp in cu_proveedores.listar_productos(db, proveedor_id)}
            if proveedor_id is not None
            else set()
        )
        costo_por_producto = {linea.producto_id: linea.costo for linea in lineas}  # una fila por producto
        for producto_id, costo in costo_por_producto.items():
            if producto_id in ya_asociados:
                resumen.existente("producto_proveedor")
                continue
            resumen.creado("producto_proveedor")
            if ejecutar:
                cu_proveedores.agregar_producto(
                    db, proveedor_id, producto_id, costo, dias_por_clave[clave]
                )


def seed_stock(
    db: Session,
    sucursales: dict[str, int | None],
    proveedores: dict[str, int | None],
    usuarios: dict[str, int | None],
    empleados: dict[str, int | None],
    compras: dict[str, list[LineaCompra]],
    ejecutar: bool,
    resumen: Resumen,
) -> None:
    from app.abastecimiento.casos_uso.cu12_registrar_recepcion_mercaderia import RegistrarRecepcionMercaderia
    from app.abastecimiento.models import OrdenCompra, Recepcion
    from app.abastecimiento.schemas import (
        OrdenCompraCrear,
        OrdenCompraDetalleCrear,
        RecepcionCrear,
        RecepcionDetalleCrear,
    )
    from app.inventario.casos_uso.cu14_consultar_inventario_global import ConsultarInventarioGlobal
    from app.inventario.models import Stock

    cu_recepcion = RegistrarRecepcionMercaderia()
    cu_inventario = ConsultarInventarioGlobal()
    admin_email = STAFF[0].email
    dias_por_clave = {p.clave: p.dias_entrega for p in PROVEEDORES}

    for s in SUCURSALES:
        encargado = next(
            (x.email for x in STAFF if x.rol == "encargado_sucursal" and x.sucursal_codigo == s.codigo), admin_email
        )
        for p in PROVEEDORES:
            lineas = compras.get(p.clave, [])
            if not lineas:
                continue
            codigo_oc = f"OC-SEED-{s.codigo.removeprefix('SC-')[:5]}-{p.clave}"
            codigo_rc = f"RC-SEED-{s.codigo.removeprefix('SC-')[:5]}-{p.clave}"
            cantidades = {
                linea.variante_id: s.cantidades.get(linea.talla, s.cantidades["otras"]) for linea in lineas
            }

            orden = db.scalar(select(OrdenCompra).where(OrdenCompra.codigo == codigo_oc))
            if orden is None:
                resumen.creado("orden_compra")
                resumen.creado("unidades", sum(cantidades.values()))
                if not ejecutar:
                    resumen.creado("recepcion")
                    continue
                orden = cu_recepcion.ordenes_compra.crear(
                    db,
                    OrdenCompraCrear(
                        codigo=codigo_oc,
                        proveedor_id=proveedores[p.clave],
                        sucursal_id=sucursales[s.codigo],
                        fecha_esperada=dt.date.today() + dt.timedelta(days=dias_por_clave[p.clave]),
                        detalle=[
                            OrdenCompraDetalleCrear(
                                variante_id=linea.variante_id,
                                cantidad=cantidades[linea.variante_id],
                                costo_unitario=linea.costo,
                            )
                            for linea in lineas
                        ],
                    ),
                    creado_por=usuarios[admin_email],
                )
                print(f"  {codigo_oc} creada ({len(lineas)} líneas, total {orden.total} Bs)")
            else:
                resumen.existente("orden_compra")

            if orden.estado == "borrador":
                if not ejecutar:
                    resumen.creado("recepcion")
                    continue
                orden = cu_recepcion.ordenes_compra.enviar(db, orden.id)

            if orden.estado in ("recibida", "anulada"):
                resumen.existente("recepcion")
                continue
            if db.scalar(select(Recepcion).where(Recepcion.codigo == codigo_rc)) is not None:
                sys.exit(f"{codigo_rc} existe pero {codigo_oc} está en '{orden.estado}': revisar a mano")

            # Recibe lo que falte de la orden (toda, salvo que alguien haya
            # cargado una recepción parcial a mano desde la app).
            recibido: dict[int, int] = defaultdict(int)
            for rec in cu_recepcion.listar(db, orden.id):
                for linea in rec.detalle:
                    recibido[linea.variante_id] += linea.cantidad
            pendientes = [
                RecepcionDetalleCrear(
                    variante_id=linea.variante_id,
                    cantidad=linea.cantidad - recibido[linea.variante_id],
                    costo_unitario=linea.costo_unitario,
                )
                for linea in orden.detalle
                if linea.cantidad > recibido[linea.variante_id]
            ]
            resumen.creado("recepcion")
            if not ejecutar or not pendientes:
                continue
            cu_recepcion.registrar(
                db,
                RecepcionCrear(
                    codigo=codigo_rc,
                    orden_compra_id=orden.id,
                    proveedor_id=orden.proveedor_id,
                    sucursal_id=orden.sucursal_id,
                    observacion="Stock inicial (seed_operativo)",
                    detalle=pendientes,
                ),
                empleado_id=empleados.get(encargado),
                creado_por=usuarios[encargado],
            )
            print(f"  {codigo_rc} recibida ({sum(d.cantidad for d in pendientes)} unidades)")

        # Límites de stock: solo donde todavía no se definieron.
        sucursal_id = sucursales[s.codigo]
        if sucursal_id is None:
            continue
        # list(): actualizar_limites_stock hace commit, no se itera un cursor abierto.
        sin_limites = list(
            db.scalars(select(Stock.id).where(Stock.sucursal_id == sucursal_id, Stock.stock_maximo.is_(None)))
        )
        resumen.creado("limites_stock", len(sin_limites))
        if ejecutar:
            for stock_id in sin_limites:
                cu_inventario.actualizar_limites(db, usuarios[admin_email], stock_id, s.stock_minimo, s.stock_maximo)


# ---- Entrada ------------------------------------------------------------------


def seed(db: Session, *, ejecutar: bool, password: str | None) -> Resumen:
    resumen = Resumen()
    ciudad_id = verificar_precondiciones(db)
    sucursales = seed_sucursales(db, ciudad_id, ejecutar, resumen)
    usuarios, empleados = seed_staff(db, sucursales, password, ejecutar, resumen)
    proveedores = seed_proveedores(db, usuarios, ejecutar, resumen)
    compras = planificar_compras(db)
    seed_producto_proveedor(db, proveedores, compras, ejecutar, resumen)
    seed_stock(db, sucursales, proveedores, usuarios, empleados, compras, ejecutar, resumen)
    return resumen


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ejecutar", action="store_true", help="Escribir de verdad (sin esto es dry-run)")
    args = parser.parse_args(argv)

    import app.main  # noqa: F401  (registra todos los modelos)
    from app.core.database import SessionLocal, engine

    print(f"Base destino: {engine.url.host}:{engine.url.port}/{engine.url.database}")

    password = os.environ.get("SEED_PASSWORD_INICIAL")
    if args.ejecutar and (password is None or len(password) < 8):
        sys.exit("Falta SEED_PASSWORD_INICIAL (mínimo 8 caracteres) para la contraseña inicial del staff")

    db = SessionLocal()
    try:
        resumen = seed(db, ejecutar=args.ejecutar, password=password)
    finally:
        db.close()

    resumen.imprimir(args.ejecutar)
    if not args.ejecutar:
        print("\n(dry-run: no se escribió nada; agregar --ejecutar)")


if __name__ == "__main__":
    main()
