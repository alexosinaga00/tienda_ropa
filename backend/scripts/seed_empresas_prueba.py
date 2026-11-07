"""Seed de las 2 empresas de prueba del multitenant (E04, D09).

  FashionStore (codigo 'fashionstore', ya existe por la migración E01):
    plan Profesional con suscripción activa; si faltan, crea los catálogos
    base, 10 productos con variantes (solo si la empresa no tiene catálogo
    propio), y con scripts.seed_operativo el administrador, 3 sucursales (2
    tiendas y 1 depósito) con horarios, staff, proveedores y stock; y 5
    clientes (los primeros de scripts.seed_demo).

  Boutique Andina (codigo 'boutique-andina'):
    plan Básico; se registra con GestionarEmpresas.registrar (que crea la
    empresa, su suscripción, el administrador y los catálogos base: 6 tallas,
    8 materiales y 9 ciudades). EXACTAMENTE 2 sucursales activas (una tienda
    y un depósito: así se puede demostrar el límite del plan al intentar la
    tercera), horarios, 1 encargado, 1 cajero, 6 productos con variantes y
    stock (recepción de mercadería), 3 clientes, 2 ventas y 1 reserva.

Los correos usan dominios distintos (fashionstore.bo y boutiqueandina.bo) y las
dos empresas tienen usuarios con el mismo nombre y el mismo correo local
(admin@..., cajero.centro@...): el correo es único POR EMPRESA.

Todas las escrituras pasan por los casos de uso y las políticas (nunca INSERT a
mano). El registro de la empresa se hace en modo plataforma; el resto, dentro
de cada empresa (core.tenant.en_empresa). Idempotente por código de empresa y
por la clave natural de cada entidad (código, correo, NIT).

Por defecto NO escribe nada (dry-run: lista lo que haría). Para escribir hace
falta --ejecutar.

Uso (desde backend/):
    python -m scripts.seed_empresas_prueba
    python -m scripts.seed_empresas_prueba --ejecutar

Variables de entorno: DATABASE_URL, JWT_SECRET_KEY (la exige Settings) y, con
--ejecutar, SEED_PASSWORD_INICIAL (contraseña inicial de todos los usuarios
creados, entre 8 y 72 caracteres). La contraseña solo se lee de la variable de
entorno: nunca se recibe por argumento ni se imprime.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, ROUND_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from scripts import seed_demo, seed_operativo
from scripts.seed_operativo import HORARIO_TIENDA, PORCENTAJE_COSTO, Resumen, StaffSeed, SucursalSeed

_DOS_DECIMALES = Decimal("0.01")

# ---- Datos -------------------------------------------------------------------------

CODIGO_FASHIONSTORE = "fashionstore"
PLAN_FASHIONSTORE = "profesional"

CODIGO_BOUTIQUE = "boutique-andina"
NOMBRE_BOUTIQUE = "Boutique Andina"
PLAN_BOUTIQUE = "basico"
DOMINIO_BOUTIQUE = "boutiqueandina.bo"
DOMINIO_DEMO_BOUTIQUE = f"demo.{DOMINIO_BOUTIQUE}"
CIUDAD_BOUTIQUE = ("La Paz", "La Paz")

CATEGORIA_PADRE = "Ropa superior"


@dataclass(frozen=True)
class ProductoSeed:
    codigo: str
    nombre: str
    categoria: str
    color: str
    precio: Decimal


COLORES: dict[str, str] = {
    "Negro": "#1A1A1A",
    "Blanco": "#F2F2F2",
    "Azul": "#1F3A5F",
    "Verde": "#2E5E3E",
    "Gris": "#8A8A8A",
    "Rojo": "#A12A2A",
    "Beige": "#D8C3A5",
    "Marron": "#6B4A2F",
}

TALLAS_FASHIONSTORE = ["M", "L", "XL"]
PRODUCTOS_FASHIONSTORE: list[ProductoSeed] = [
    ProductoSeed("FSP-001", "Polera Nike Basic (Negro)", "Poleras", "Negro", Decimal("149.00")),
    ProductoSeed("FSP-002", "Polera Adidas Essentials (Blanco)", "Poleras", "Blanco", Decimal("149.00")),
    ProductoSeed("FSP-003", "Polo Puma Classic (Azul)", "Poleras", "Azul", Decimal("189.00")),
    ProductoSeed("FSP-004", "Polo Lacoste Pique (Verde)", "Poleras", "Verde", Decimal("189.00")),
    ProductoSeed("FSP-005", "Camiseta Fila Sport (Gris)", "Poleras", "Gris", Decimal("149.00")),
    ProductoSeed("FSP-006", "Polera Reebok Training (Rojo)", "Poleras", "Rojo", Decimal("149.00")),
    ProductoSeed("FSP-007", "Chamarra Adidas Wind (Negro)", "Chamarras", "Negro", Decimal("399.00")),
    ProductoSeed("FSP-008", "Chamarra Puma Urban (Azul)", "Chamarras", "Azul", Decimal("399.00")),
    ProductoSeed("FSP-009", "Chamarra Nike Storm (Gris)", "Chamarras", "Gris", Decimal("399.00")),
    ProductoSeed("FSP-010", "Polo Under Armour Tech (Negro)", "Poleras", "Negro", Decimal("189.00")),
]
# Los 5 primeros clientes de la demo (scripts.seed_demo): mismos datos y correos.
CLIENTES_FASHIONSTORE = seed_demo.CLIENTES[:5]

TALLAS_BOUTIQUE = ["S", "M", "L"]
PRODUCTOS_BOUTIQUE: list[ProductoSeed] = [
    ProductoSeed("BAP-001", "Chompa de Alpaca Andina (Beige)", "Chompas", "Beige", Decimal("320.00")),
    ProductoSeed("BAP-002", "Chompa Tejida Cusco (Gris)", "Chompas", "Gris", Decimal("280.00")),
    ProductoSeed("BAP-003", "Camisa de Lino Andina (Blanco)", "Camisas", "Blanco", Decimal("210.00")),
    ProductoSeed("BAP-004", "Camisa Cuadros Altiplano (Azul)", "Camisas", "Azul", Decimal("190.00")),
    ProductoSeed("BAP-005", "Chamarra Poncho Urbano (Marron)", "Chamarras", "Marron", Decimal("450.00")),
    ProductoSeed("BAP-006", "Polera Estampado Tiwanaku (Negro)", "Poleras", "Negro", Decimal("130.00")),
]
# Los 3 primeros clientes de la demo con el dominio de la boutique: mismos nombres
# y mismo correo local (cliente01@...) que los de FashionStore, otra empresa.
CLIENTES_BOUTIQUE = seed_demo.CLIENTES[:3]

SUCURSALES_BOUTIQUE: list[SucursalSeed] = [
    SucursalSeed(
        "LP-CENTRO", "Boutique Andina Centro", "Av. 16 de Julio 1550, El Prado", "22123456",
        Decimal("-16.4955000"), Decimal("-68.1336000"), False,
        {"S": 8, "M": 8, "L": 8, "otras": 6}, 3, 30,
    ),
    SucursalSeed(
        "LP-DEPOSITO", "Deposito Andino", "Zona Villa Adela, Calle 3", "22654321",
        Decimal("-16.5000000"), Decimal("-68.1500000"), True,
        {"S": 15, "M": 15, "L": 15, "otras": 10}, 5, 60,
    ),
]

STAFF_BOUTIQUE: list[StaffSeed] = [
    StaffSeed(f"admin@{DOMINIO_BOUTIQUE}", "Administrador", "General", "71000001", "administrador", "", "Administrador", "9100001"),
    StaffSeed(f"encargado.centro@{DOMINIO_BOUTIQUE}", "Carla", "Rojas", "71000002", "encargado_sucursal", "LP-CENTRO", "Encargada de sucursal", "9100002"),
    StaffSeed(f"cajero.centro@{DOMINIO_BOUTIQUE}", "Diego", "Suarez", "71000003", "cajero", "LP-CENTRO", "Cajero", "9100003"),
]
ADMIN_BOUTIQUE = STAFF_BOUTIQUE[0]
NIT_PROVEEDOR_BOUTIQUE = "2030405011"
TIENDA_BOUTIQUE = SUCURSALES_BOUTIQUE[0]
VENTAS_BOUTIQUE = 2
RESERVAS_BOUTIQUE = 1


def _email_cliente_boutique(numero: int) -> str:
    return f"cliente{numero:02d}@{DOMINIO_DEMO_BOUTIQUE}"


# ---- Apoyo ---------------------------------------------------------------------------


def _validar_password(password: str | None) -> str:
    """La contraseña inicial: entre 8 y 72 caracteres (el máximo de bcrypt).
    Los mensajes nunca la incluyen."""
    if password is None or len(password) < 8 or len(password.encode("utf-8")) > 72:
        sys.exit("Falta SEED_PASSWORD_INICIAL (entre 8 y 72 caracteres) para la contraseña inicial de los usuarios")
    return password


def _fusionar(destino: Resumen, origen: Resumen) -> None:
    for entidad, n in origen.creados.items():
        destino.creado(entidad, n)
    for entidad, n in origen.existentes.items():
        destino.existente(entidad, n)


@dataclass
class EstadoEmpresa:
    """Lo que ya tiene una empresa, leído dentro de ella."""

    plan_codigo: str | None
    estado: str | None  # estado efectivo de la suscripción vigente
    admin_existe: bool
    base_completa: bool  # ciudades, tallas y materiales base


def _leer_estado(db: Session, empresa_id: int, admin_email: str | None) -> EstadoEmpresa:
    from app.catalogo.models import Material, Talla
    from app.catalogo.politicas import MATERIALES_BASE, TALLAS_BASE
    from app.core.tenant import en_empresa
    from app.plataforma import politicas
    from app.plataforma.models import Ciudad, Usuario

    with en_empresa(db, empresa_id):
        vigente = politicas.obtener_suscripcion_vigente(db)
        plan = politicas.plan_de_la_empresa(db)
        plan_codigo = plan.codigo if plan is not None else None
        estado = politicas.estado_efectivo(vigente) if vigente is not None else None
        admin_existe = (
            admin_email is not None and db.scalar(select(Usuario.id).where(Usuario.email == admin_email)) is not None
        )
        ciudades = {(c, d) for c, d in db.execute(select(Ciudad.nombre, Ciudad.departamento))}
        tallas = set(db.scalars(select(Talla.codigo)))
        materiales = set(db.scalars(select(Material.nombre)))
    base = (
        set(politicas.CIUDADES_BASE) <= ciudades
        and {t[0] for t in TALLAS_BASE} <= tallas
        and set(MATERIALES_BASE) <= materiales
    )
    return EstadoEmpresa(plan_codigo, estado, admin_existe, base)


def verificar_precondiciones(db: Session) -> None:
    """Planes y datos globales (roles, tipos de movimiento, estados, métodos de
    pago) que otros seeds o las migraciones dejan sembrados."""
    from app.catalogo.models import TipoMovimiento
    from app.comercial.models import EstadoReserva, MetodoPago
    from app.plataforma.models import Plan, Rol

    errores: list[str] = []
    planes = set(db.scalars(select(Plan.codigo).where(Plan.activo.is_(True))))
    for codigo in (PLAN_FASHIONSTORE, PLAN_BOUTIQUE):
        if codigo not in planes:
            errores.append(f"Falta el plan '{codigo}' (correr scripts.seed_planes)")
    roles = set(db.scalars(select(Rol.nombre).where(Rol.activo.is_(True))))
    necesarios = {s.rol for s in seed_operativo.STAFF} | {s.rol for s in STAFF_BOUTIQUE} | {"cliente"}
    if necesarios - roles:
        errores.append(f"Faltan los roles {sorted(necesarios - roles)} (correr scripts.seed_seguridad)")
    if db.scalar(select(TipoMovimiento.id).where(TipoMovimiento.codigo == "recepcion")) is None:
        errores.append("Falta el tipo de movimiento 'recepcion' (correr scripts.seed_inventario)")
    if db.scalar(select(func.count()).select_from(EstadoReserva)) == 0:
        errores.append("Faltan los estados de reserva (correr scripts.seed_reservas)")
    if db.scalar(select(func.count()).select_from(MetodoPago)) == 0:
        errores.append("Faltan los métodos de pago (correr scripts.seed_pagos)")
    # Boutique Andina registra ventas pagadas: necesita los estados de venta y de pago, que son
    # globales y los siembran seed_ventas y seed_pagos (solo se comprobaba que hubiera métodos de pago).
    from app.comercial.models import EstadoPago, EstadoVenta

    if db.scalar(select(EstadoVenta.id).where(EstadoVenta.codigo == "pendiente_pago")) is None:
        errores.append("Faltan los estados de venta (correr scripts.seed_ventas)")
    if db.scalar(select(EstadoPago.id).where(EstadoPago.codigo == "iniciado")) is None:
        errores.append("Faltan los estados de pago (correr scripts.seed_pagos)")
    if errores:
        sys.exit("Precondiciones no cumplidas:\n  - " + "\n  - ".join(errores))


def _asegurar_base(db: Session, empresa_id: int, estado: EstadoEmpresa, ejecutar: bool, resumen: Resumen) -> None:
    """Ciudades, tallas y materiales base (los inicializadores de la empresa
    nueva, idempotentes)."""
    if estado.base_completa:
        resumen.existente("catalogos_base")
        return
    resumen.creado("catalogos_base")
    if ejecutar:
        from app.core.tenant import inicializar_empresa

        inicializar_empresa(db, empresa_id)
        db.commit()


def _asegurar_plan(
    db: Session, empresa_id: int, plan_codigo: str, estado: EstadoEmpresa, ejecutar: bool, resumen: Resumen
) -> None:
    """Sin suscripción vigente asigna el plan. Con una suscripción de otro plan
    o que no está activa NO la toca (es una decisión del superadministrador): solo
    avisa. Se llama en modo plataforma."""
    if estado.plan_codigo is None:
        resumen.creado("suscripcion")
        if ejecutar:
            from app.plataforma.casos_uso.cu04_gestionar_empresas_planes_suscripciones import GestionarSuscripciones
            from app.plataforma.schemas import SuscripcionAsignar

            GestionarSuscripciones().asignar_o_cambiar_plan(
                db, SuscripcionAsignar(empresa_id=empresa_id, plan_codigo=plan_codigo)
            )
            print(f"  suscripción {plan_codigo} asignada")
        return
    resumen.existente("suscripcion")
    if estado.plan_codigo != plan_codigo or estado.estado != "activa":
        print(
            f"  AVISO: la suscripción vigente es '{estado.plan_codigo}' ({estado.estado}); "
            f"la semilla espera '{plan_codigo}' activa. No se modifica."
        )


# ---- Catálogo --------------------------------------------------------------------------


def _sembrar_productos(
    db: Session,
    productos: list[ProductoSeed],
    tallas: list[str],
    ejecutar: bool,
    resumen: Resumen,
    *,
    solo_sin_catalogo_propio: bool = False,
) -> None:
    """Categorías, colores y productos con sus variantes (talla x color) por el
    CU-05. Con `solo_sin_catalogo_propio`, si la empresa ya tiene productos que no
    son de la semilla (p. ej. el catálogo real de FashionStore) no agrega nada."""
    from app.catalogo.casos_uso.cu05_gestionar_catalogo import (
        GestionarCategorias,
        GestionarColores,
        GestionarProductos,
    )
    from app.catalogo.models import Categoria, Color, Producto, Talla
    from app.catalogo.schemas import CategoriaCrear, ColorCrear, ProductoCrear

    codigos = [p.codigo for p in productos]
    existentes = set(db.scalars(select(Producto.codigo).where(Producto.codigo.in_(codigos))))
    if solo_sin_catalogo_propio:
        ajenos = db.scalar(select(func.count()).select_from(Producto).where(Producto.codigo.not_in(codigos))) or 0
        if ajenos:
            resumen.existente("producto", ajenos)
            print(f"  la empresa ya tiene {ajenos} productos propios: no se agregan los de la semilla")
            return
    resumen.existente("producto", len(existentes))
    faltan = [p for p in productos if p.codigo not in existentes]
    if not faltan:
        return

    cu_categorias, cu_colores, cu_productos = GestionarCategorias(), GestionarColores(), GestionarProductos()

    def categoria(nombre: str, padre_id: int | None) -> int | None:
        fila = db.scalar(select(Categoria).where(Categoria.nombre == nombre))
        if fila is not None:
            resumen.existente("categoria")
            return fila.id
        resumen.creado("categoria")
        if not ejecutar:
            return None
        return cu_categorias.crear(db, CategoriaCrear(nombre=nombre, categoria_padre_id=padre_id)).id

    def color(nombre: str) -> int | None:
        fila = db.scalar(select(Color).where(Color.nombre == nombre))
        if fila is not None:
            resumen.existente("color")
            return fila.id
        resumen.creado("color")
        if not ejecutar:
            return None
        return cu_colores.crear(db, ColorCrear(nombre=nombre, codigo_hex=COLORES[nombre])).id

    padre_id = categoria(CATEGORIA_PADRE, None)
    categorias = {n: categoria(n, padre_id) for n in dict.fromkeys(p.categoria for p in faltan)}
    colores = {n: color(n) for n in dict.fromkeys(p.color for p in faltan)}

    ids_talla = {t.codigo: t.id for t in db.scalars(select(Talla).where(Talla.codigo.in_(tallas)))}
    if ejecutar and set(tallas) - set(ids_talla):
        sys.exit(f"Faltan las tallas {sorted(set(tallas) - set(ids_talla))} (catálogos base de la empresa)")
    for p in faltan:
        resumen.creado("producto")
        resumen.creado("variante", len(tallas))
        if not ejecutar:
            continue
        cu_productos.crear(
            db,
            ProductoCrear(
                codigo=p.codigo, nombre=p.nombre, categoria_id=categorias[p.categoria], genero="hombre",
                precio_base=p.precio, tallas_ids=[ids_talla[t] for t in tallas], colores_ids=[colores[p.color]],
            ),
            creado_por=None,
        )
        print(f"  producto {p.codigo} creado")


# ---- Clientes ---------------------------------------------------------------------------


def _sembrar_clientes(
    db: Session,
    clientes: list,
    email_de,
    password: str | None,
    ejecutar: bool,
    resumen: Resumen,
) -> dict[int, int | None]:
    """Clientes con su perfil (CU-01). `email_de(numero)` da el correo de cada
    uno. Devuelve el usuario_id por número de cliente."""
    from app.plataforma.casos_uso.cu01_autenticar_registrar_usuarios import RegistrarCliente
    from app.plataforma.models import Cliente, Usuario
    from app.plataforma.schemas import ClientePerfilActualizar, RegistroRequest

    cu_clientes = RegistrarCliente()
    usuarios: dict[int, int | None] = {}
    for c in clientes:
        email = email_de(c.numero)
        usuario = db.scalar(select(Usuario).where(Usuario.email == email))
        if usuario is None:
            resumen.creado("cliente")
            if ejecutar:
                usuario = cu_clientes.registrar(
                    db,
                    RegistroRequest(
                        nombre=c.nombre, apellido=c.apellido, email=email,
                        telefono=f"7{c.numero:02d}45678", password=password, ci_nit=c.ci,
                    ),
                )
                print(f"  cliente {email} creado")
        else:
            resumen.existente("cliente")
        usuarios[c.numero] = usuario.id if usuario is not None else None
        if usuario is None:
            resumen.creado("cliente.perfil")
            continue
        perfil = db.scalar(select(Cliente).where(Cliente.usuario_id == usuario.id))
        if perfil is not None and perfil.estatura_cm is None:
            resumen.creado("cliente.perfil")
            if ejecutar:
                cu_clientes.actualizar_perfil(
                    db,
                    usuario.id,
                    ClientePerfilActualizar(
                        razon_social=c.razon_social, fecha_nacimiento=c.nacimiento,
                        estatura_cm=c.estatura, preferencia_ajuste=c.ajuste,
                    ),
                )
        else:
            resumen.existente("cliente.perfil")
    return usuarios


# ---- FashionStore ------------------------------------------------------------------------


def _sembrar_operativo_fashionstore(db: Session, ejecutar: bool, password: str | None, resumen: Resumen) -> None:
    """Sucursales, horarios, staff, proveedores y stock: es scripts.seed_operativo
    (los datos de FashionStore). Si todavía no hay variantes ni ciudad (dry-run
    antes de crear el catálogo) solo se informa lo que se crearía."""
    from app.catalogo.models import ProductoVariante
    from app.plataforma.models import Ciudad

    simulable = (
        db.scalar(
            select(Ciudad.id).where(
                Ciudad.nombre == seed_operativo.CIUDAD_NOMBRE,
                Ciudad.departamento == seed_operativo.CIUDAD_DEPARTAMENTO,
            )
        )
        is not None
        and db.scalar(select(ProductoVariante.id).limit(1)) is not None
    )
    if ejecutar or simulable:
        _fusionar(resumen, seed_operativo.seed(db, ejecutar=ejecutar, password=password))
        return
    staff = seed_operativo.STAFF
    previsto = {
        "sucursal": len(seed_operativo.SUCURSALES),
        "horario_sucursal": len(HORARIO_TIENDA) * sum(not s.es_deposito for s in seed_operativo.SUCURSALES),
        "usuario": len(staff),
        "usuario_rol": len(staff),
        "empleado": sum(s.sucursal_codigo is not None for s in staff),
        "proveedor": len(seed_operativo.PROVEEDORES),
        "orden_compra": len(seed_operativo.SUCURSALES) * len(seed_operativo.PROVEEDORES),
        "recepcion": len(seed_operativo.SUCURSALES) * len(seed_operativo.PROVEEDORES),
    }
    for entidad, n in previsto.items():
        resumen.creado(entidad, n)


def sembrar_fashionstore(db: Session, ejecutar: bool, password: str | None) -> Resumen:
    from app.core.tenant import en_empresa
    from app.plataforma.politicas import obtener_empresa_por_codigo

    empresa = obtener_empresa_por_codigo(db, CODIGO_FASHIONSTORE)
    if empresa is None:
        sys.exit(f"No existe la empresa '{CODIGO_FASHIONSTORE}' (la crea la migración multitenant E01)")
    if not empresa.activo:
        sys.exit(f"La empresa '{CODIGO_FASHIONSTORE}' está inactiva: reactivarla antes de seguir")
    empresa_id = empresa.id

    resumen = Resumen()
    resumen.existente("empresa")
    estado = _leer_estado(db, empresa_id, None)
    _asegurar_base(db, empresa_id, estado, ejecutar, resumen)
    _asegurar_plan(db, empresa_id, PLAN_FASHIONSTORE, estado, ejecutar, resumen)
    with en_empresa(db, empresa_id):
        _sembrar_productos(
            db, PRODUCTOS_FASHIONSTORE, TALLAS_FASHIONSTORE, ejecutar, resumen, solo_sin_catalogo_propio=True
        )
        _sembrar_operativo_fashionstore(db, ejecutar, password, resumen)
        _sembrar_clientes(db, CLIENTES_FASHIONSTORE, seed_demo.email_cliente, password, ejecutar, resumen)
    return resumen


# ---- Boutique Andina -----------------------------------------------------------------------


def _registrar_boutique(db: Session, password: str | None, ejecutar: bool, resumen: Resumen) -> int | None:
    """Registra la empresa (modo plataforma). Devuelve su id, o None en dry-run
    si todavía no existe."""
    from app.plataforma.casos_uso.cu04_gestionar_empresas_planes_suscripciones import GestionarEmpresas
    from app.plataforma.politicas import obtener_empresa_por_codigo
    from app.plataforma.schemas import AdministradorRegistrar, EmpresaRegistrar

    empresa = obtener_empresa_por_codigo(db, CODIGO_BOUTIQUE)
    if empresa is not None:
        if not empresa.activo:
            sys.exit(f"La empresa '{CODIGO_BOUTIQUE}' está inactiva: reactivarla antes de seguir")
        resumen.existente("empresa")
        return empresa.id
    resumen.creado("empresa")
    resumen.creado("suscripcion")
    resumen.creado("usuario")  # el administrador
    resumen.creado("usuario_rol")
    resumen.creado("catalogos_base")
    if not ejecutar:
        return None
    respuesta = GestionarEmpresas().registrar(
        db,
        EmpresaRegistrar(
            nombre=NOMBRE_BOUTIQUE,
            plan_codigo=PLAN_BOUTIQUE,
            administrador=AdministradorRegistrar(
                nombre=ADMIN_BOUTIQUE.nombre,
                apellido=ADMIN_BOUTIQUE.apellido,
                email=ADMIN_BOUTIQUE.email,
                telefono=ADMIN_BOUTIQUE.telefono,
                password=password,
            ),
        ),
    )
    print(f"  empresa {respuesta.codigo} registrada id={respuesta.id} (plan {respuesta.plan_codigo})")
    return respuesta.id


def _asegurar_administrador(db: Session, empresa_id: int, password: str | None, ejecutar: bool) -> None:
    """Si la empresa ya existía pero le falta su administrador (modo plataforma)."""
    from app.plataforma.casos_uso.cu04_gestionar_empresas_planes_suscripciones import GestionarEmpresas
    from app.plataforma.schemas import AdministradorRegistrar

    if ejecutar:
        GestionarEmpresas().agregar_administrador(
            db,
            empresa_id,
            AdministradorRegistrar(
                nombre=ADMIN_BOUTIQUE.nombre, apellido=ADMIN_BOUTIQUE.apellido, email=ADMIN_BOUTIQUE.email,
                telefono=ADMIN_BOUTIQUE.telefono, password=password,
            ),
        )
        print(f"  administrador {ADMIN_BOUTIQUE.email} creado")


def _variantes_de(db: Session, productos: list[ProductoSeed]) -> list[tuple[int, str, Decimal]]:
    """(variante_id, código de talla, precio) de las variantes activas de los
    productos de la semilla, en orden estable."""
    from app.catalogo.models import Producto, ProductoVariante, Talla

    filas = db.execute(
        select(ProductoVariante.id, Talla.codigo, ProductoVariante.precio, Producto.precio_base)
        .join(Producto, Producto.id == ProductoVariante.producto_id)
        .join(Talla, Talla.id == ProductoVariante.talla_id)
        .where(Producto.codigo.in_([p.codigo for p in productos]), ProductoVariante.activo.is_(True))
        .order_by(ProductoVariante.id)
    ).all()
    return [(vid, talla, precio if precio is not None else base) for vid, talla, precio, base in filas]


def _sembrar_stock_boutique(
    db: Session,
    sucursales: dict[str, int | None],
    usuarios: dict[str, int | None],
    empleados: dict[str, int | None],
    ejecutar: bool,
    resumen: Resumen,
) -> None:
    """Un proveedor y una recepción de mercadería por sucursal (el stock queda
    respaldado por el kardex). Sin orden de compra: la recepción directa."""
    from app.catalogo.casos_uso.cu08_gestionar_abastecimiento import GestionarProveedores, RegistrarRecepcionMercaderia
    from app.catalogo.models import Proveedor, Recepcion
    from app.catalogo.schemas import ProveedorCrear, RecepcionCrear, RecepcionDetalleCrear

    proveedor = db.scalar(select(Proveedor).where(Proveedor.nit == NIT_PROVEEDOR_BOUTIQUE))
    if proveedor is not None and not proveedor.activo:
        sys.exit(f"El proveedor NIT {NIT_PROVEEDOR_BOUTIQUE} existe pero está inactivo: reactivarlo a mano")
    if proveedor is None:
        resumen.creado("proveedor")
        if ejecutar:
            proveedor = GestionarProveedores().crear(
                db,
                ProveedorCrear(
                    nombre="Tejidos del Altiplano SRL", nit=NIT_PROVEEDOR_BOUTIQUE, contacto="Rosa Quispe",
                    telefono="22111222", email="ventas@tejidosaltiplano.bo", direccion="Calle Illampu 450, La Paz",
                ),
            )
    else:
        resumen.existente("proveedor")
    proveedor_id = proveedor.id if proveedor is not None else None

    variantes = _variantes_de(db, PRODUCTOS_BOUTIQUE)
    cu_recepcion = RegistrarRecepcionMercaderia()
    encargado = next(s.email for s in STAFF_BOUTIQUE if s.rol == "encargado_sucursal")
    for s in SUCURSALES_BOUTIQUE:
        codigo_rc = f"RC-BA-{s.codigo.removeprefix('LP-')[:10]}"
        if db.scalar(select(Recepcion.id).where(Recepcion.codigo == codigo_rc)) is not None:
            resumen.existente("recepcion")
            continue
        resumen.creado("recepcion")
        resumen.creado("unidades", sum(s.cantidades.get(talla, s.cantidades["otras"]) for _, talla, _ in variantes))
        if not ejecutar:
            continue
        recibe = encargado if not s.es_deposito else ADMIN_BOUTIQUE.email
        cu_recepcion.registrar(
            db,
            RecepcionCrear(
                codigo=codigo_rc,
                proveedor_id=proveedor_id,
                sucursal_id=sucursales[s.codigo],
                observacion="Stock inicial (seed_empresas_prueba)",
                detalle=[
                    RecepcionDetalleCrear(
                        variante_id=vid,
                        cantidad=s.cantidades.get(talla, s.cantidades["otras"]),
                        costo_unitario=(precio * PORCENTAJE_COSTO).quantize(_DOS_DECIMALES, rounding=ROUND_HALF_UP),
                    )
                    for vid, talla, precio in variantes
                ],
            ),
            empleado_id=empleados.get(recibe),
            creado_por=usuarios[recibe],
        )
        print(f"  {codigo_rc} recibida ({len(variantes)} variantes)")


def _variantes_con_stock(db: Session, sucursal_id: int, minimo: int) -> list[int]:
    from app.catalogo.models import Stock

    return list(
        db.scalars(
            select(Stock.variante_id)
            .where(Stock.sucursal_id == sucursal_id, Stock.cantidad_disponible >= minimo)
            .order_by(Stock.variante_id)
        )
    )


def _sembrar_operacion_boutique(
    db: Session,
    sucursales: dict[str, int | None],
    usuarios: dict[str, int | None],
    clientes: dict[int, int | None],
    ejecutar: bool,
    resumen: Resumen,
) -> None:
    """2 ventas presenciales pagadas en caja y 1 reserva de ejemplo. Se hacen una
    sola vez: si la empresa ya tiene ventas (o reservas) se omiten."""
    from app.comercial.politicas import crear_reserva
    from app.comercial.casos_uso.cu14_registrar_venta_presencial import RegistrarVentaPresencial
    from app.comercial.casos_uso.cu18_procesar_pagos import ProcesarPagoCaja
    from app.comercial.models import Reserva, Venta
    from app.comercial.schemas import (
        PagoCajaRequest,
        ReservaCrear,
        ReservaDetalleCrear,
        VentaDetalleLinea,
        VentaPresencialCrear,
    )
    from app.plataforma.politicas import obtener_horario_dia, obtener_perfil_cliente

    hay_ventas = bool(db.scalar(select(func.count()).select_from(Venta)))
    hay_reservas = bool(db.scalar(select(func.count()).select_from(Reserva)))
    for entidad, n, ya in (
        ("venta_presencial", VENTAS_BOUTIQUE, hay_ventas),
        ("reserva", RESERVAS_BOUTIQUE, hay_reservas),
    ):
        (resumen.existente if ya else resumen.creado)(entidad, n)
    if not ejecutar or (hay_ventas and hay_reservas):
        return

    tienda = sucursales[TIENDA_BOUTIQUE.codigo]
    cajero = usuarios[next(s.email for s in STAFF_BOUTIQUE if s.rol == "cajero")]
    disponibles = _variantes_con_stock(db, tienda, 3)
    if len(disponibles) < 5:
        sys.exit("No hay stock suficiente en la tienda para las ventas y la reserva de ejemplo")

    if not hay_ventas:
        cu_venta, cu_pago = RegistrarVentaPresencial(), ProcesarPagoCaja()
        ventas = [
            # (variantes, cantidad por línea, cliente, método)
            (disponibles[0:2], 1, clientes[1], "qr"),
            (disponibles[2:3], 2, None, "efectivo"),
        ]
        for variantes, cantidad, cliente_usuario, metodo in ventas:
            cliente_id = obtener_perfil_cliente(db, cliente_usuario).id if cliente_usuario is not None else None
            venta = cu_venta.ejecutar(
                db,
                cajero,
                VentaPresencialCrear(
                    sucursal_id=tienda,
                    detalle=[VentaDetalleLinea(variante_id=v, cantidad=cantidad) for v in variantes],
                    cliente_id=cliente_id,
                ),
            )
            recibido = venta.total.quantize(Decimal("1"), rounding=ROUND_UP) if metodo == "efectivo" else None
            cu_pago.ejecutar(db, cajero, PagoCajaRequest(venta_id=venta.id, metodo_pago=metodo, monto_recibido=recibido))
            print(f"  venta {venta.id} pagada ({metodo})")

    if not hay_reservas:
        fecha = dt.date.today() + dt.timedelta(days=2)
        for _ in range(8):  # el primer día con horario de atención
            if obtener_horario_dia(db, tienda, fecha.isoweekday()) is not None:
                break
            fecha += dt.timedelta(days=1)
        # Datos de ejemplo: se crean sin los topes que `ReservarPrendas` le pone a un cliente real.
        reserva = crear_reserva(
            db,
            clientes[2],
            ReservaCrear(
                sucursal_id=tienda,
                fecha_visita=fecha,
                hora_visita_desde=dt.time(10, 0),
                hora_visita_hasta=dt.time(11, 0),
                observacion="Reserva de ejemplo (seed_empresas_prueba)",
                detalle=[ReservaDetalleCrear(variante_id=v) for v in disponibles[3:5]],
            ),
        )
        print(f"  reserva {reserva.codigo} para el {fecha}")


def _resumen_previsto_boutique(resumen: Resumen) -> None:
    """Dry-run con la empresa todavía inexistente: lo que se crearía dentro."""
    variantes = len(PRODUCTOS_BOUTIQUE) * len(TALLAS_BOUTIQUE)
    previsto = {
        "sucursal": len(SUCURSALES_BOUTIQUE),
        "horario_sucursal": len(HORARIO_TIENDA) * sum(not s.es_deposito for s in SUCURSALES_BOUTIQUE),
        "usuario": len(STAFF_BOUTIQUE) - 1,
        "usuario_rol": len(STAFF_BOUTIQUE) - 1,
        "empleado": sum(s.sucursal_codigo is not None for s in STAFF_BOUTIQUE),
        "categoria": 1 + len({p.categoria for p in PRODUCTOS_BOUTIQUE}),
        "color": len({p.color for p in PRODUCTOS_BOUTIQUE}),
        "producto": len(PRODUCTOS_BOUTIQUE),
        "variante": variantes,
        "proveedor": 1,
        "recepcion": len(SUCURSALES_BOUTIQUE),
        "cliente": len(CLIENTES_BOUTIQUE),
        "cliente.perfil": len(CLIENTES_BOUTIQUE),
        "venta_presencial": VENTAS_BOUTIQUE,
        "reserva": RESERVAS_BOUTIQUE,
    }
    for entidad, n in previsto.items():
        resumen.creado(entidad, n)


def sembrar_boutique(db: Session, ejecutar: bool, password: str | None) -> Resumen:
    from app.core.tenant import en_empresa
    from app.plataforma.models import Ciudad

    resumen = Resumen()
    empresa_id = _registrar_boutique(db, password, ejecutar, resumen)
    if empresa_id is None:  # dry-run y la empresa no existe
        _resumen_previsto_boutique(resumen)
        return resumen

    estado = _leer_estado(db, empresa_id, ADMIN_BOUTIQUE.email)
    _asegurar_base(db, empresa_id, estado, ejecutar, resumen)
    _asegurar_plan(db, empresa_id, PLAN_BOUTIQUE, estado, ejecutar, resumen)
    if not estado.admin_existe:
        _asegurar_administrador(db, empresa_id, password, ejecutar)

    with en_empresa(db, empresa_id):
        ciudad_id = db.scalar(
            select(Ciudad.id).where(Ciudad.nombre == CIUDAD_BOUTIQUE[0], Ciudad.departamento == CIUDAD_BOUTIQUE[1])
        )
        if ciudad_id is None:
            if not ejecutar:
                _resumen_previsto_boutique(resumen)
                return resumen
            sys.exit(f"Falta la ciudad {CIUDAD_BOUTIQUE[0]} en la empresa '{CODIGO_BOUTIQUE}'")
        sucursales = seed_operativo.seed_sucursales(db, ciudad_id, ejecutar, resumen, SUCURSALES_BOUTIQUE)
        usuarios, empleados = seed_operativo.seed_staff(
            db, sucursales, password, ejecutar, resumen, staff=STAFF_BOUTIQUE
        )
        _sembrar_productos(db, PRODUCTOS_BOUTIQUE, TALLAS_BOUTIQUE, ejecutar, resumen)
        _sembrar_stock_boutique(db, sucursales, usuarios, empleados, ejecutar, resumen)
        clientes = _sembrar_clientes(db, CLIENTES_BOUTIQUE, _email_cliente_boutique, password, ejecutar, resumen)
        _sembrar_operacion_boutique(db, sucursales, usuarios, clientes, ejecutar, resumen)
    return resumen


# ---- Entrada --------------------------------------------------------------------------------


def seed(db: Session, *, ejecutar: bool, password: str | None) -> dict[str, Resumen]:
    """Siembra las 2 empresas. Devuelve el resumen por código de empresa. La
    sesión puede venir fijada en una empresa: se pasa a modo plataforma (para
    registrar la empresa) y al terminar se deja como estaba."""
    from app.core.tenant import empresa_de, en_modo_plataforma, fijar_empresa, fijar_plataforma

    if ejecutar:
        _validar_password(password)
    anterior, era_plataforma = empresa_de(db), en_modo_plataforma(db)
    fijar_plataforma(db)
    try:
        verificar_precondiciones(db)
        print("FashionStore")
        fashionstore = sembrar_fashionstore(db, ejecutar, password)
        print("Boutique Andina")
        boutique = sembrar_boutique(db, ejecutar, password)
    finally:
        if era_plataforma:
            fijar_plataforma(db)
        else:
            fijar_empresa(db, anterior)
    return {CODIGO_FASHIONSTORE: fashionstore, CODIGO_BOUTIQUE: boutique}


def imprimir(resultados: dict[str, Resumen], ejecutar: bool) -> None:
    for codigo, resumen in resultados.items():
        print(f"\n== {codigo} ==")
        resumen.imprimir(ejecutar)
    if not ejecutar:
        print("\n(dry-run: no se escribió nada; agregar --ejecutar)")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ejecutar", action="store_true", help="Escribir de verdad (sin esto es dry-run)")
    args = parser.parse_args(argv)

    import app.main  # noqa: F401  (registra todos los modelos)
    from app.core.database import SessionLocal, engine

    print(f"Base destino: {engine.url.host}:{engine.url.port}/{engine.url.database}")

    password = os.environ.get("SEED_PASSWORD_INICIAL")
    if args.ejecutar:
        _validar_password(password)

    db = SessionLocal()
    try:
        resultados = seed(db, ejecutar=args.ejecutar, password=password)
    finally:
        db.close()
    imprimir(resultados, args.ejecutar)


if __name__ == "__main__":
    main()
