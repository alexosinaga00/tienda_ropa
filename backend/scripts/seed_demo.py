"""Seed de datos de demostración: completa lo que los otros seeds no cargan
para que la app, el back office y los reportes muestren datos reales.

  1. Maestros: temporadas 2026, colecciones, material/colección de cada
     producto, código de barras EAN-13, tablas de medida y descripciones.
  2. Clientes demo con perfil completo y direcciones de envío.
  3. Promociones (dos vigentes y una vencida).
  4. Operación: transferencias desde el depósito, ventas presenciales en
     caja, ventas digitales (retiro y envío) con sus envíos, devoluciones,
     reservas en distintos estados (una convertida en venta) e historial de
     navegación.
  5. Reparte las fechas de lo creado en el paso 4 entre la última recepción
     de stock y ahora, para que los reportes no muestren todo "hoy".

Todas las escrituras pasan por los services (mismas reglas de negocio que la
app: stock reservado/descontado, costo congelado al pagar, transiciones de
estado válidas). La única excepción es el paso 5: un UPDATE de fechas solo
sobre las filas que este script acaba de crear.

Idempotente: los maestros, clientes y promociones se buscan por clave
natural. El paso 4 se hace una sola vez: si ya existe la transferencia
TRF-DEMO-01, se asume cargado y se omite (el kardex no se "deshace").

Requiere los seeds anteriores: scripts.seed_todo, scripts.seed_prendas_probador
y scripts.seed_operativo (sucursales, staff, stock).

Por defecto NO escribe nada (dry-run). Para escribir hace falta --ejecutar.

Uso (desde backend/):
    python -m scripts.seed_demo
    python -m scripts.seed_demo --ejecutar

Variables de entorno: DATABASE_URL, JWT_SECRET_KEY y, con --ejecutar,
SEED_PASSWORD_INICIAL (contraseña de los clientes demo, mínimo 8 caracteres).
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import random
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

DOMINIO_STAFF = "fashionstore.bo"
DOMINIO_DEMO = "demo.fashionstore.bo"
MARCA_OPERACION = "TRF-DEMO-01"
HOY = dt.date.today()

TEMPORADAS = [
    # (nombre, año, inicio, fin)
    ("Invierno", 2026, dt.date(2026, 6, 1), dt.date(2026, 8, 31)),
    ("Primavera", 2026, dt.date(2026, 9, 1), dt.date(2026, 11, 30)),
]

COLECCIONES = {
    # categoría -> (colección, temporada, descripción)
    "Poleras": ("Urbana Primavera 2026", ("Primavera", 2026), "Poleras livianas para el día a día en la ciudad."),
    "Chamarras": ("Abrigo Invierno 2026", ("Invierno", 2026), "Chamarras y abrigos para los días frescos."),
}

# Material por categoría: se alterna entre las dos opciones según el producto.
MATERIALES_POR_CATEGORIA = {"Poleras": ("Algodon", "Poliester"), "Chamarras": ("Poliester", "Cuero sintetico")}

DESCRIPCION_CATEGORIA = {
    "Ropa superior": "Prendas superiores masculinas: poleras, camisas y chamarras.",
    "Poleras": "Poleras de manga corta y larga, deportivas y urbanas.",
    "Chamarras": "Chamarras, casacas y abrigos.",
}
DESCRIPCION_MATERIAL = {
    "Algodon": "Fibra natural, fresca y suave al tacto.",
    "Hilo": "Tejido de punto fino, liviano.",
    "Poliester": "Sintético resistente, de secado rápido.",
    "Lino": "Fibra natural muy fresca, ideal para calor.",
    "Mezclilla": "Algodón tejido en sarga, resistente.",
    "Lana": "Fibra natural abrigada.",
    "Seda": "Fibra natural brillante y liviana.",
    "Cuero sintetico": "Imitación de cuero, repele el agua.",
}

# Medidas de talla hombre (cm): pecho min/max, cintura min/max, hombros, largo.
MEDIDAS = {
    "XS": (82, 88, 68, 74, 40, 66),
    "S": (88, 94, 74, 80, 42, 68),
    "M": (94, 100, 80, 86, 44, 70),
    "L": (100, 106, 86, 92, 46, 72),
    "XL": (106, 112, 92, 98, 48, 74),
    "XXL": (112, 118, 98, 104, 50, 76),
}


@dataclass(frozen=True)
class ClienteDemo:
    numero: int
    nombre: str
    apellido: str
    ci: str
    razon_social: str | None
    nacimiento: dt.date
    estatura: int
    ajuste: str
    direcciones: list[tuple[str, str, str, int]]  # (alias, dirección, referencia, anillo)


CLIENTES = [
    ClienteDemo(1, "Andrés", "Paz", "7810011", None, dt.date(1995, 3, 14), 178, "regular",
                [("Casa", "Calle Florida 230", "Frente al parque", 1)]),
    ClienteDemo(2, "Bruno", "Roca", "7810022", "Roca Importaciones", dt.date(1990, 7, 2), 182, "holgado",
                [("Casa", "Av. Beni 1450", "Edificio Torres, piso 3", 3), ("Trabajo", "Av. Monseñor Rivero 520", None, 2)]),
    ClienteDemo(3, "Carlos", "Añez", "7810033", None, dt.date(2000, 11, 21), 170, "ajustado",
                [("Casa", "Barrio Hamacas, calle 5", "Casa verde", 4)]),
    ClienteDemo(4, "Daniel", "Cuéllar", "7810044", None, dt.date(1988, 1, 9), 175, "regular",
                [("Casa", "Av. Piraí 3er anillo", None, 3)]),
    ClienteDemo(5, "Esteban", "Vargas", "7810055", "EV Consultores", dt.date(1993, 5, 30), 185, "holgado",
                [("Trabajo", "Equipetrol Norte, calle 9", "Oficina 402", 2)]),
    ClienteDemo(6, "Fernando", "Molina", "7810066", None, dt.date(1999, 9, 17), 168, "ajustado",
                [("Casa", "Villa 1ro de Mayo, UV 45", None, 5)]),
    ClienteDemo(7, "Gabriel", "Saucedo", "7810077", None, dt.date(1985, 12, 3), 180, "regular",
                [("Casa", "Av. Banzer 4to anillo", "Condominio Los Pinos", 4)]),
    ClienteDemo(8, "Hugo", "Terrazas", "7810088", None, dt.date(2002, 4, 25), 173, "regular",
                [("Casa", "Calle Ingavi 88", None, 1)]),
    ClienteDemo(9, "Iván", "Ribera", "7810099", None, dt.date(1997, 8, 11), 188, "holgado",
                [("Casa", "Av. Grigotá 2do anillo", None, 2)]),
    ClienteDemo(10, "Jorge", "Lijerón", "7810100", "Lijerón y Asociados", dt.date(1991, 2, 6), 176, "ajustado",
                [("Trabajo", "Av. San Martín 1100", "Torre Empresarial", 2)]),
]


def email_cliente(numero: int) -> str:
    return f"cliente{numero:02d}@{DOMINIO_DEMO}"


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
        print(f"\n{'entidad':26} {verbo:>10} {'ya existían':>12}")
        for entidad in dict.fromkeys([*self.creados, *self.existentes]):
            print(f"{entidad:26} {self.creados.get(entidad, 0):>10} {self.existentes.get(entidad, 0):>12}")


# ---- Contexto ------------------------------------------------------------------


@dataclass
class Contexto:
    sucursales: dict[str, int]  # código -> id
    tiendas: list[int]  # sucursales que atienden al público
    deposito: int | None
    cajeros: dict[int, int]  # sucursal_id -> usuario_id del cajero
    encargados: dict[int, int]  # sucursal_id -> usuario_id del encargado
    admin_usuario_id: int
    categorias: dict[str, int]
    tallas: dict[int, str]  # talla_id -> código


def cargar_contexto(db: Session) -> Contexto:
    from app.catalogo.models import Categoria, ProductoVariante, Talla
    from app.organizacion.models import Empleado, Sucursal
    from app.seguridad.models import Usuario

    errores: list[str] = []
    sucursales = {s.codigo: s for s in db.scalars(select(Sucursal).where(Sucursal.activo.is_(True)))}
    tiendas = [s.id for s in sucursales.values() if not s.es_deposito]
    deposito = next((s.id for s in sucursales.values() if s.es_deposito), None)
    if len(tiendas) < 1:
        errores.append("No hay sucursales que atiendan al público (correr scripts.seed_operativo)")

    cajeros: dict[int, int] = {}
    encargados: dict[int, int] = {}
    for emp in db.scalars(select(Empleado).where(Empleado.activo.is_(True), Empleado.sucursal_id.is_not(None))):
        cargo = (emp.cargo or "").lower()
        if "cajer" in cargo:
            cajeros.setdefault(emp.sucursal_id, emp.usuario_id)
        elif "encargad" in cargo:
            encargados.setdefault(emp.sucursal_id, emp.usuario_id)
    for tienda in tiendas:
        if tienda not in cajeros:
            errores.append(f"La sucursal id={tienda} no tiene cajero (correr scripts.seed_operativo)")

    admin = db.scalar(select(Usuario).where(Usuario.email == f"admin@{DOMINIO_STAFF}"))
    if admin is None:
        errores.append(f"Falta el usuario admin@{DOMINIO_STAFF} (correr scripts.seed_operativo)")

    if db.scalar(select(func.count()).select_from(ProductoVariante)) == 0:
        errores.append("No hay variantes (correr scripts.seed_prendas_probador)")

    if errores:
        sys.exit("Precondiciones no cumplidas:\n  - " + "\n  - ".join(errores))

    return Contexto(
        sucursales={codigo: s.id for codigo, s in sucursales.items()},
        tiendas=tiendas,
        deposito=deposito,
        cajeros=cajeros,
        encargados={t: encargados.get(t, admin.id) for t in tiendas},
        admin_usuario_id=admin.id,
        categorias={c.nombre: c.id for c in db.scalars(select(Categoria))},
        tallas={t.id: t.codigo for t in db.scalars(select(Talla))},
    )


# ---- 1. Maestros ---------------------------------------------------------------


def ean13(variante_id: int) -> str:
    base = f"777{variante_id:09d}"
    suma = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(base))
    return base + str((10 - suma % 10) % 10)


def seed_maestros(db: Session, ctx: Contexto, ejecutar: bool, resumen: Resumen) -> None:
    from app.catalogo.casos_uso.cu07_gestionar_catalogo_maestro import (
        GestionarCategorias,
        GestionarColecciones,
        GestionarMateriales,
        GestionarTemporadas,
    )
    from app.catalogo.casos_uso.cu08_gestionar_productos import GestionarProductos
    from app.catalogo.models import Categoria, Coleccion, Material, Producto, ProductoVariante, TablaMedida, Temporada
    from app.catalogo.schemas import (
        CategoriaActualizar,
        ColeccionCrear,
        MaterialActualizar,
        ProductoActualizar,
        TablaMedidaCrear,
        TemporadaCrear,
        VarianteActualizar,
    )

    cu_categorias = GestionarCategorias()
    cu_colecciones = GestionarColecciones()
    cu_materiales = GestionarMateriales()
    cu_temporadas = GestionarTemporadas()
    cu_productos = GestionarProductos()

    temporadas: dict[tuple[str, int], int | None] = {}
    for nombre, anio, inicio, fin in TEMPORADAS:
        t = db.scalar(select(Temporada).where(Temporada.nombre == nombre, Temporada.anio == anio))
        if t is None:
            resumen.creado("temporada")
            if ejecutar:
                t = cu_temporadas.crear(
                    db, TemporadaCrear(nombre=nombre, anio=anio, fecha_inicio=inicio, fecha_fin=fin)
                )
        else:
            resumen.existente("temporada")
        temporadas[(nombre, anio)] = t.id if t is not None else None

    colecciones: dict[str, int | None] = {}
    for categoria, (nombre, temporada, descripcion) in COLECCIONES.items():
        c = db.scalar(select(Coleccion).where(Coleccion.nombre == nombre))
        if c is None:
            resumen.creado("coleccion")
            if ejecutar:
                c = cu_colecciones.crear(
                    db, ColeccionCrear(nombre=nombre, temporada_id=temporadas[temporada], descripcion=descripcion)
                )
        else:
            resumen.existente("coleccion")
        colecciones[categoria] = c.id if c is not None else None

    materiales = {m.nombre: m for m in db.scalars(select(Material))}
    for nombre, descripcion in DESCRIPCION_MATERIAL.items():
        m = materiales.get(nombre)
        if m is not None and not m.descripcion:
            resumen.creado("material.descripcion")
            if ejecutar:
                cu_materiales.actualizar(db, m.id, MaterialActualizar(descripcion=descripcion))
    for c in list(db.scalars(select(Categoria))):
        if not c.descripcion and c.nombre in DESCRIPCION_CATEGORIA:
            resumen.creado("categoria.descripcion")
            if ejecutar:
                cu_categorias.actualizar(db, c.id, CategoriaActualizar(descripcion=DESCRIPCION_CATEGORIA[c.nombre]))

    nombre_categoria = {v: k for k, v in ctx.categorias.items()}
    productos = list(db.scalars(select(Producto).where(Producto.activo.is_(True)).order_by(Producto.id)))
    con_medidas = set(db.scalars(select(TablaMedida.producto_id).where(TablaMedida.producto_id.is_not(None))))
    for i, p in enumerate(productos):
        categoria = nombre_categoria.get(p.categoria_id, "")
        cambios: dict = {}
        opciones = MATERIALES_POR_CATEGORIA.get(categoria)
        if p.material_id is None and opciones and opciones[i % 2] in materiales:
            cambios["material_id"] = materiales[opciones[i % 2]].id
        if p.coleccion_id is None and colecciones.get(categoria):
            cambios["coleccion_id"] = colecciones[categoria]
        if cambios:
            resumen.creado("producto.material/coleccion")
            if ejecutar:
                cu_productos.actualizar(db, p.id, ProductoActualizar(**cambios))
        elif p.material_id is not None:
            resumen.existente("producto.material/coleccion")

        variantes = list(db.scalars(select(ProductoVariante).where(ProductoVariante.producto_id == p.id)))
        for v in variantes:
            if v.codigo_barras:
                resumen.existente("variante.codigo_barras")
                continue
            resumen.creado("variante.codigo_barras")
            if ejecutar:
                cu_productos.actualizar_variante(db, v.id, VarianteActualizar(codigo_barras=ean13(v.id)))

        if p.id in con_medidas:
            resumen.existente("tabla_medida", len({v.talla_id for v in variantes}))
            continue
        extra_largo = 2 if categoria == "Chamarras" else 0
        for talla_id in sorted({v.talla_id for v in variantes}):
            codigo = ctx.tallas.get(talla_id)
            if codigo not in MEDIDAS:
                continue
            pmin, pmax, cmin, cmax, hombros, largo = MEDIDAS[codigo]
            resumen.creado("tabla_medida")
            if ejecutar:
                cu_productos.crear_medida(
                    db,
                    p.id,
                    TablaMedidaCrear(
                        talla_id=talla_id,
                        pecho_min_cm=Decimal(pmin), pecho_max_cm=Decimal(pmax),
                        cintura_min_cm=Decimal(cmin), cintura_max_cm=Decimal(cmax),
                        hombros_cm=Decimal(hombros), largo_cm=Decimal(largo + extra_largo),
                    ),
                )


# ---- 2. Clientes ---------------------------------------------------------------


def seed_clientes(db: Session, password: str | None, ejecutar: bool, resumen: Resumen) -> dict[int, int | None]:
    """Devuelve usuario_id por número de cliente demo."""
    from app.entregas.casos_uso.cu42_solicitar_envio_domicilio import SolicitarEnvioDomicilio
    from app.entregas.models import DireccionCliente, ZonaEnvio
    from app.entregas.schemas import DireccionClienteCrear

    cu_solicitar_envio = SolicitarEnvioDomicilio()
    from app.seguridad.casos_uso.cu01_registrar_cliente import RegistrarCliente
    from app.seguridad.models import Cliente, Usuario
    from app.seguridad.schemas import ClientePerfilActualizar, RegistroRequest

    cu_registrar_cliente = RegistrarCliente()

    zonas = list(db.scalars(select(ZonaEnvio).where(ZonaEnvio.activo.is_(True)).order_by(ZonaEnvio.anillo_desde)))

    def zona_para(anillo: int) -> int | None:
        for z in zonas:
            if (z.anillo_desde or 0) <= anillo and (z.anillo_hasta is None or anillo <= z.anillo_hasta):
                return z.id
        return zonas[-1].id if zonas else None

    usuarios: dict[int, int | None] = {}
    for c in CLIENTES:
        usuario = db.scalar(select(Usuario).where(Usuario.email == email_cliente(c.numero)))
        if usuario is None:
            resumen.creado("cliente")
            if ejecutar:
                usuario = cu_registrar_cliente.registrar(
                    db,
                    RegistroRequest(
                        nombre=c.nombre, apellido=c.apellido, email=email_cliente(c.numero),
                        telefono=f"7{c.numero:02d}45678", password=password, ci_nit=c.ci,
                    ),
                )
                print(f"  cliente {email_cliente(c.numero)} creado id={usuario.id}")
        else:
            resumen.existente("cliente")
        usuarios[c.numero] = usuario.id if usuario is not None else None
        if usuario is None:
            resumen.creado("cliente.perfil")
            resumen.creado("direccion_cliente", len(c.direcciones))
            continue

        perfil = db.scalar(select(Cliente).where(Cliente.usuario_id == usuario.id))
        if perfil.estatura_cm is None:
            resumen.creado("cliente.perfil")
            if ejecutar:
                cu_registrar_cliente.actualizar_perfil(
                    db,
                    usuario.id,
                    ClientePerfilActualizar(
                        razon_social=c.razon_social, fecha_nacimiento=c.nacimiento,
                        estatura_cm=c.estatura, preferencia_ajuste=c.ajuste,
                    ),
                )
        else:
            resumen.existente("cliente.perfil")

        if db.scalar(select(func.count()).select_from(DireccionCliente).where(DireccionCliente.cliente_id == perfil.id)):
            resumen.existente("direccion_cliente", len(c.direcciones))
            continue
        for i, (alias, direccion, referencia, anillo) in enumerate(c.direcciones):
            resumen.creado("direccion_cliente")
            if ejecutar:
                cu_solicitar_envio.crear_mi_direccion(
                    db,
                    usuario.id,
                    DireccionClienteCrear(
                        alias=alias, direccion=direccion, referencia=referencia,
                        zona_envio_id=zona_para(anillo), es_principal=i == 0,
                    ),
                )
    return usuarios


# ---- 3. Promociones ------------------------------------------------------------


def seed_promociones(db: Session, ctx: Contexto, ejecutar: bool, resumen: Resumen) -> None:
    from app.catalogo.models import Temporada
    from app.ventas.casos_uso.cu27_gestionar_promociones import GestionarPromociones
    from app.ventas.models import Promocion
    from app.ventas.schemas import PromocionAlcanceCrear, PromocionCrear

    cu_promociones = GestionarPromociones()
    invierno = db.scalar(select(Temporada.id).where(Temporada.nombre == "Invierno", Temporada.anio == 2026))
    promociones = [
        ("Poleras 15%", "porcentaje", Decimal("15"), dt.date(2026, 9, 1), dt.date(2026, 11, 30),
         PromocionAlcanceCrear(categoria_id=ctx.categorias.get("Poleras"))),
        ("Chamarras -Bs 30", "monto", Decimal("30"), dt.date(2026, 9, 1), dt.date(2026, 10, 31),
         PromocionAlcanceCrear(categoria_id=ctx.categorias.get("Chamarras"))),
        ("Liquidación invierno 25%", "porcentaje", Decimal("25"), dt.date(2026, 7, 15), dt.date(2026, 8, 31),
         PromocionAlcanceCrear(temporada_id=invierno) if invierno else None),
    ]
    for nombre, tipo, valor, inicio, fin, alcance in promociones:
        if db.scalar(select(Promocion).where(Promocion.nombre == nombre)) is not None:
            resumen.existente("promocion")
            continue
        resumen.creado("promocion")
        if not ejecutar:
            continue
        if alcance is None or all(x is None for x in (alcance.categoria_id, alcance.temporada_id, alcance.producto_id)):
            print(f"  (se omite '{nombre}': falta su categoría/temporada)")
            continue
        cu_promociones.crear(
            db, PromocionCrear(nombre=nombre, tipo=tipo, valor=valor, fecha_inicio=inicio, fecha_fin=fin, alcances=[alcance])
        )


# ---- 4. Operación --------------------------------------------------------------


@dataclass
class Creado:
    """Lo creado en el paso 4, en orden cronológico, para repartir fechas."""

    eventos: list[tuple[str, int]] = field(default_factory=list)  # (tipo, id)
    historial_ids: list[int] = field(default_factory=list)


def _variantes_con_stock(db: Session, sucursal_id: int, minimo: int) -> list[int]:
    from app.inventario.models import Stock

    return list(
        db.scalars(
            select(Stock.variante_id)
            .where(Stock.sucursal_id == sucursal_id, Stock.cantidad_disponible >= minimo)
            .order_by(Stock.variante_id)
        )
    )


def seed_operacion(
    db: Session, ctx: Contexto, clientes: dict[int, int | None], ejecutar: bool, resumen: Resumen
) -> Creado:
    from app.entregas.casos_uso.cu42_solicitar_envio_domicilio import SolicitarEnvioDomicilio
    from app.entregas.casos_uso.cu43_actualizar_estado_envio import ActualizarEstadoEnvio
    from app.entregas.models import DireccionCliente
    from app.entregas.schemas import CotizarEnvioRequest, EnvioCrear, EnvioEstadoActualizar
    from app.inteligencia.politicas import registrar_evento
    from app.inteligencia.schemas import EventoCrear
    from app.inventario.casos_uso.cu15_registrar_movimiento_inventario import RegistrarMovimientoInventario
    from app.inventario.models import Transferencia
    from app.inventario.schemas import TransferenciaCrear, TransferenciaDetalleCrear
    from app.pagos.casos_uso.cu30_procesar_pago_caja import ProcesarPagoCaja
    from app.pagos.schemas import PagoCajaRequest
    from app.reservas.casos_uso.cu16_reservar_prendas import ReservarPrendas
    from app.reservas.casos_uso.cu18_cancelar_reserva import CancelarReserva
    from app.reservas.casos_uso.cu20_atender_prueba_reserva_sucursal import AtenderPruebaReservaSucursal
    from app.reservas.schemas import ReservaCrear, ReservaDetalleCrear, SeleccionActualizar, SeleccionLinea
    from app.seguridad.models import Usuario
    from app.seguridad.politicas import obtener_perfil_cliente
    from app.ventas.casos_uso.cu23_gestionar_carrito import GestionarCarrito
    from app.ventas.casos_uso.cu24_realizar_compra_digital import RealizarCompraDigital
    from app.ventas.casos_uso.cu25_registrar_venta_presencial import RegistrarVentaPresencial
    from app.ventas.casos_uso.cu40_registrar_devolucion import RegistrarDevolucion
    from app.ventas.politicas import obtener_venta
    from app.ventas.schemas import (
        CarritoDetalleCrear,
        DevolucionCrear,
        DevolucionDetalleCrear,
        VentaDetalleLinea,
        VentaDigitalCrear,
        VentaPresencialCrear,
    )

    cu_solicitar_envio = SolicitarEnvioDomicilio()
    cu_actualizar_estado_envio = ActualizarEstadoEnvio()
    cu_transferencias = RegistrarMovimientoInventario()
    cu_pago_caja = ProcesarPagoCaja()
    cu_reservar = ReservarPrendas()
    cu_cancelar_reserva = CancelarReserva()
    cu_atender_reserva = AtenderPruebaReservaSucursal()
    cu_carrito = GestionarCarrito()
    cu_compra_digital = RealizarCompraDigital()
    cu_venta_presencial = RegistrarVentaPresencial()
    cu_devolucion = RegistrarDevolucion()

    creado = Creado()
    plan = {"transferencia": 4, "venta_presencial": 15, "venta_digital": 10, "envio": 5, "devolucion": 3,
            "reserva": 5, "historial_navegacion": 150}

    if db.scalar(select(Transferencia).where(Transferencia.codigo == MARCA_OPERACION)) is not None:
        for entidad, n in plan.items():
            resumen.existente(entidad, n)
        print(f"  operación demo ya cargada ({MARCA_OPERACION} existe): se omite")
        return creado
    if not ejecutar:
        for entidad, n in plan.items():
            resumen.creado(entidad, n)
        return creado
    if any(uid is None for uid in clientes.values()):
        sys.exit("Faltan clientes demo: no se puede cargar la operación")

    rnd = random.Random(2026)
    cliente_ids = {
        n: obtener_perfil_cliente(db, uid).id for n, uid in clientes.items() if uid is not None
    }

    def pagar(venta_id: int, sucursal_id: int, total: Decimal) -> None:
        metodo = rnd.choice(["efectivo", "qr", "tarjeta"])
        recibido = (total + Decimal(rnd.choice([0, 1, 10, 50]))).quantize(Decimal("1")) if metodo == "efectivo" else None
        if recibido is not None and recibido < total:
            recibido += 1
        cu_pago_caja.ejecutar(
            db, ctx.cajeros[sucursal_id], PagoCajaRequest(venta_id=venta_id, metodo_pago=metodo, monto_recibido=recibido)
        )

    # 4.1 Transferencias desde el depósito (recibidas, en tránsito, anulada).
    if ctx.deposito is not None:
        stock_deposito = _variantes_con_stock(db, ctx.deposito, 6)
        rnd.shuffle(stock_deposito)
        destinos = ctx.tiendas * 2
        for n, estado in enumerate(["recibida", "recibida", "en_transito", "anulada"], start=1):
            lineas = stock_deposito[(n - 1) * 3 : (n - 1) * 3 + 3]
            if not lineas:
                break
            t = cu_transferencias.crear_transferencia(
                db,
                TransferenciaCrear(
                    codigo=f"TRF-DEMO-{n:02d}",
                    sucursal_origen_id=ctx.deposito,
                    sucursal_destino_id=destinos[(n - 1) % len(destinos)],
                    detalle=[TransferenciaDetalleCrear(variante_id=v, cantidad=2) for v in lineas],
                ),
                ctx.admin_usuario_id,
            )
            if estado == "anulada":
                cu_transferencias.anular_transferencia(db, ctx.admin_usuario_id, t.id)
            else:
                cu_transferencias.enviar_transferencia(db, t.id, ctx.admin_usuario_id)
                if estado == "recibida":
                    cu_transferencias.recibir_transferencia(db, t.id, ctx.encargados[t.sucursal_destino_id])
            creado.eventos.append(("transferencia", t.id))
            resumen.creado("transferencia")
            print(f"  {t.codigo} -> {estado}")

    # 4.2 Ventas presenciales en caja (algunas con cliente identificado).
    ventas_pagadas: list[int] = []
    for n in range(15):
        sucursal = ctx.tiendas[n % len(ctx.tiendas)]
        disponibles = _variantes_con_stock(db, sucursal, 2)
        if not disponibles:
            continue
        lineas = rnd.sample(disponibles, k=min(len(disponibles), rnd.choice([1, 1, 2])))
        venta = cu_venta_presencial.ejecutar(
            db,
            ctx.cajeros[sucursal],
            VentaPresencialCrear(
                sucursal_id=sucursal,
                detalle=[VentaDetalleLinea(variante_id=v, cantidad=rnd.choice([1, 1, 2])) for v in lineas],
                cliente_id=cliente_ids[rnd.randint(1, 10)] if n % 3 == 0 else None,
            ),
        )
        pagar(venta.id, sucursal, venta.total)
        ventas_pagadas.append(venta.id)
        creado.eventos.append(("venta", venta.id))
        resumen.creado("venta_presencial")

    # 4.3 Ventas digitales pagadas: retiro en tienda o envío (el envío lo
    # puede despachar cualquier sucursal con stock, incluido el depósito).
    usuarios = {n: db.get(Usuario, uid) for n, uid in clientes.items()}
    envios_creados: list[int] = []
    for n in range(10):
        numero = n + 1
        usuario_id = clientes[numero]
        con_envio = n % 2 == 1
        origenes = [*ctx.tiendas, *([ctx.deposito] if con_envio and ctx.deposito else [])]
        sucursal = origenes[n % len(origenes)]
        disponibles = _variantes_con_stock(db, sucursal, 2)
        if not disponibles:
            continue
        variantes = rnd.sample(disponibles, k=min(len(disponibles), rnd.choice([1, 2])))
        for v in variantes:
            cu_carrito.agregar(db, usuario_id, CarritoDetalleCrear(variante_id=v, cantidad=1))

        costo_envio = Decimal("0")
        direccion_id = None
        if con_envio:
            direccion_id = db.scalar(
                select(DireccionCliente.id)
                .where(DireccionCliente.cliente_id == cliente_ids[numero], DireccionCliente.es_principal.is_(True))
            )
            costo_envio = cu_solicitar_envio.cotizar(
                db, CotizarEnvioRequest(direccion_id=direccion_id, cantidad_prendas=len(variantes))
            ).costo
        venta = cu_compra_digital.ejecutar(
            db, usuario_id, VentaDigitalCrear(sucursal_id=sucursal, costo_envio=costo_envio)
        )
        # Pago confirmado sin pasarela externa (equivalente a un pago aprobado).
        # El depósito no tiene cajero: lo cobra el admin (alcance global), no
        # el cajero de otra sucursal.
        cu_pago_caja.ejecutar(
            db,
            ctx.cajeros.get(sucursal) or ctx.admin_usuario_id,
            PagoCajaRequest(venta_id=venta.id, metodo_pago="qr"),
        )
        ventas_pagadas.append(venta.id)
        creado.eventos.append(("venta", venta.id))
        resumen.creado("venta_digital")
        if con_envio and direccion_id is not None:
            envio = cu_solicitar_envio.crear_envio(db, usuario_id, EnvioCrear(venta_id=venta.id, direccion_id=direccion_id))
            envios_creados.append(envio.id)
            resumen.creado("envio")

    repartidores = ["Marco Flores", "Rodrigo Chávez"]
    for i, envio_id in enumerate(envios_creados):
        destino = ["programado", "en_ruta", "entregado", "entregado", "fallido"][i % 5]
        pasos = {"programado": [], "en_ruta": ["en_ruta"], "entregado": ["en_ruta", "entregado"],
                 "fallido": ["en_ruta", "fallido"]}[destino]
        for paso in pasos:
            cu_actualizar_estado_envio.actualizar_estado(
                db, ctx.admin_usuario_id, envio_id, EnvioEstadoActualizar(estado=paso, repartidor=repartidores[i % 2])
            )

    # 4.4 Devoluciones parciales sobre ventas pagadas.
    motivos = ["La talla no le quedó", "Cambio de opinión del cliente", "Detalle de costura"]
    for i, venta_id in enumerate(ventas_pagadas[1:12:4][:3]):
        venta = obtener_venta(db, venta_id)
        linea = venta.detalle[0]
        encargado = ctx.encargados.get(venta.sucursal_id, ctx.admin_usuario_id)
        dev = cu_devolucion.ejecutar(
            db,
            encargado,
            DevolucionCrear(
                venta_id=venta_id, motivo=motivos[i],
                detalle=[DevolucionDetalleCrear(venta_detalle_id=linea.id, cantidad=1)],
            ),
        )
        creado.eventos.append(("devolucion", dev.id))
        resumen.creado("devolucion")

    # 4.5 Reservas: pendiente, preparada, vencida (la vence la tarea
    # periódica), cancelada y una completada que se factura en caja con
    # reserva_id (para la tasa de conversión). No se deja ninguna
    # 'completada' sin facturar: seguiría reteniendo stock.
    tienda = ctx.tiendas[0]
    encargado = ctx.encargados[tienda]

    def fecha_con_horario(desde: dt.date, paso: int) -> dt.date:
        from app.organizacion.politicas import obtener_horario_dia

        fecha = desde
        for _ in range(8):
            if obtener_horario_dia(db, tienda, fecha.isoweekday()) is not None:
                return fecha
            fecha += dt.timedelta(days=paso)
        return desde

    escenarios = [
        ("pendiente", fecha_con_horario(HOY + dt.timedelta(days=2), 1), 3),
        ("preparada", fecha_con_horario(HOY + dt.timedelta(days=1), 1), 4),
        ("vencida", fecha_con_horario(HOY - dt.timedelta(days=3), -1), 5),
        ("facturada", fecha_con_horario(HOY, -1), 6),
        ("cancelada", fecha_con_horario(HOY + dt.timedelta(days=4), 1), 7),
    ]
    for estado, fecha, numero in escenarios:
        disponibles = _variantes_con_stock(db, tienda, 2)
        if len(disponibles) < 2:
            break
        variantes = rnd.sample(disponibles, k=2)
        reserva = cu_reservar.ejecutar(
            db,
            clientes[numero],
            ReservaCrear(
                sucursal_id=tienda, fecha_visita=fecha,
                hora_visita_desde=dt.time(10, 0), hora_visita_hasta=dt.time(11, 0),
                observacion="Reserva de demostración",
                detalle=[ReservaDetalleCrear(variante_id=v) for v in variantes],
            ),
        )
        if estado == "cancelada":
            cu_cancelar_reserva.ejecutar(db, reserva.id, clientes[numero])
        if estado in ("preparada", "facturada"):
            cu_atender_reserva.preparar(db, reserva.id, encargado)
        if estado == "facturada":
            cu_atender_reserva.confirmar_llegada(db, reserva.id, encargado)
            cu_atender_reserva.registrar_seleccion(
                db, reserva.id, encargado,
                SeleccionActualizar(lineas=[SeleccionLinea(variante_id=variantes[0], seleccionada=True),
                                            SeleccionLinea(variante_id=variantes[1], seleccionada=False)]),
            )
        if estado == "facturada":
            venta = cu_venta_presencial.ejecutar(
                db, ctx.cajeros[tienda], VentaPresencialCrear(sucursal_id=tienda, reserva_id=reserva.id)
            )
            pagar(venta.id, tienda, venta.total)
            creado.eventos.append(("venta", venta.id))
        resumen.creado("reserva")
        print(f"  {reserva.codigo} ({estado}, visita {fecha})")

    # 4.6 Historial de navegación de los clientes demo (señal para el recomendador).
    from app.catalogo.models import ProductoVariante
    from app.inteligencia.models import HistorialNavegacion

    variantes = list(db.execute(select(ProductoVariante.id, ProductoVariante.producto_id)).all())
    tipos = ["vista"] * 6 + ["busqueda"] * 2 + ["carrito"] * 2 + ["favorito", "probador"]
    antes = db.scalar(select(func.coalesce(func.max(HistorialNavegacion.id), 0)))
    for _ in range(150):
        numero = rnd.randint(1, 10)
        variante_id, producto_id = rnd.choice(variantes)
        tipo = rnd.choice(tipos)
        registrar_evento(
            db,
            EventoCrear(
                tipo_evento=tipo,
                producto_id=None if tipo == "busqueda" else producto_id,
                variante_id=variante_id if tipo in ("carrito", "favorito", "probador") else None,
            ),
            usuarios[numero],
        )
        resumen.creado("historial_navegacion")
    creado.historial_ids = list(
        db.scalars(select(HistorialNavegacion.id).where(HistorialNavegacion.id > antes).order_by(HistorialNavegacion.id))
    )
    return creado


# ---- 5. Fechas -----------------------------------------------------------------


def repartir_fechas(db: Session, creado: Creado) -> None:
    """Reparte lo creado entre la última recepción de stock y ahora, en el
    mismo orden en que se creó (nunca antes de que el stock existiera)."""
    from app.inventario.models import MovimientoInventario, Transferencia
    from app.inteligencia.models import HistorialNavegacion
    from app.pagos.models import Pago
    from app.ventas.models import Devolucion, Venta

    if not creado.eventos:
        return
    ahora = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) - dt.timedelta(minutes=10)
    ultima_recepcion = db.scalar(
        select(func.max(MovimientoInventario.creado_en)).where(MovimientoInventario.referencia_tipo == "recepcion")
    )
    inicio = max((ultima_recepcion or ahora - dt.timedelta(days=30)) + dt.timedelta(hours=1), ahora - dt.timedelta(days=30))
    if inicio >= ahora:
        print("  (sin margen de tiempo para repartir fechas: quedan con la fecha actual)")
        return

    rnd = random.Random(7)
    rango = (ahora - inicio).total_seconds()
    marcas = sorted(inicio + dt.timedelta(seconds=rnd.random() * rango) for _ in creado.eventos)

    for (tipo, id_), cuando in zip(creado.eventos, marcas):
        if tipo == "venta":
            db.execute(update(Venta).where(Venta.id == id_).values(fecha=cuando))
            db.execute(update(Pago).where(Pago.venta_id == id_).values(fecha=cuando))
            db.execute(
                update(MovimientoInventario)
                .where(MovimientoInventario.referencia_tipo == "venta", MovimientoInventario.referencia_id == id_)
                .values(creado_en=cuando)
            )
        elif tipo == "devolucion":
            db.execute(update(Devolucion).where(Devolucion.id == id_).values(fecha=cuando))
            db.execute(
                update(MovimientoInventario)
                .where(MovimientoInventario.referencia_tipo == "devolucion", MovimientoInventario.referencia_id == id_)
                .values(creado_en=cuando)
            )
        elif tipo == "transferencia":
            t = db.get(Transferencia, id_)
            db.execute(
                update(Transferencia)
                .where(Transferencia.id == id_)
                .values(
                    fecha_envio=cuando if t.fecha_envio else None,
                    fecha_recepcion=cuando + dt.timedelta(hours=3) if t.fecha_recepcion else None,
                )
            )
            db.execute(
                update(MovimientoInventario)
                .where(MovimientoInventario.referencia_tipo == "transferencia", MovimientoInventario.referencia_id == id_)
                .values(creado_en=cuando)
            )

    for id_ in creado.historial_ids:
        cuando = inicio + dt.timedelta(seconds=rnd.random() * rango)
        db.execute(update(HistorialNavegacion).where(HistorialNavegacion.id == id_).values(creado_en=cuando))
    db.commit()
    print(f"  fechas repartidas entre {inicio:%Y-%m-%d %H:%M} y {ahora:%Y-%m-%d %H:%M} (UTC)")


# ---- Entrada ------------------------------------------------------------------


def seed(db: Session, *, ejecutar: bool, password: str | None) -> Resumen:
    resumen = Resumen()
    ctx = cargar_contexto(db)
    print("1. Maestros")
    seed_maestros(db, ctx, ejecutar, resumen)
    print("2. Clientes")
    clientes = seed_clientes(db, password, ejecutar, resumen)
    print("3. Promociones")
    seed_promociones(db, ctx, ejecutar, resumen)
    print("4. Operación")
    creado = seed_operacion(db, ctx, clientes, ejecutar, resumen)
    if ejecutar:
        print("5. Fechas")
        repartir_fechas(db, creado)
    return resumen


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ejecutar", action="store_true", help="Escribir de verdad (sin esto es dry-run)")
    args = parser.parse_args(argv)

    # La tarea periódica del backend no corre dentro del script.
    os.environ.setdefault("TAREAS_AUTOMATICAS", "false")
    import app.main  # noqa: F401  (registra todos los modelos)
    from app.core.database import SessionLocal, engine

    print(f"Base destino: {engine.url.host}:{engine.url.port}/{engine.url.database}")

    password = os.environ.get("SEED_PASSWORD_INICIAL")
    if args.ejecutar and (password is None or len(password) < 8):
        sys.exit("Falta SEED_PASSWORD_INICIAL (mínimo 8 caracteres) para la contraseña de los clientes demo")

    db = SessionLocal()
    try:
        db.execute(text("select 1"))
        resumen = seed(db, ejecutar=args.ejecutar, password=password)
    finally:
        db.close()

    resumen.imprimir(args.ejecutar)
    if not args.ejecutar:
        print("\n(dry-run: no se escribió nada; agregar --ejecutar)")


if __name__ == "__main__":
    main()
