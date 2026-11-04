"""Reglas y consultas del paquete `catalogo` (secciones Catálogo, Inventario y
Probador) que no son casos de uso del catálogo: producto, variante, talla,
tabla_medida, stock, movimientos y generaciones del probador. Las usan los casos
de uso de este mismo paquete y los paquetes `comercial` e `inteligencia`, para
que nadie tenga que consultar esas tablas directamente.
"""

import io
from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal

from PIL import Image, UnidentifiedImageError
from sqlalchemy.orm import Session

from app.catalogo.models import (
    Categoria,
    Material,
    MovimientoInventario,
    ProbadorGeneracion,
    Producto,
    ProductoVariante,
    Stock,
    TablaMedida,
    Talla,
    Temporada,
)
from app.catalogo.repository import (
    CategoriaRepository,
    ColorRepository,
    GeneracionRepository,
    MaterialRepository,
    MovimientoRepository,
    ProductoRepository,
    StockRepository,
    TablaMedidaRepository,
    TallaRepository,
    TemporadaRepository,
    TipoMovimientoRepository,
    VarianteRepository,
    existencias_por_producto,
)
from app.catalogo.schemas import CatalogoItemRespuesta, FiltrosCatalogo, Genero, ValoresReferenciaCatalogo
from app.core import storage
from app.core.deps import ParametrosPeriodo
from app.core.exceptions import ConflictoError, DomainError, NoEncontradoError, StockInsuficienteError
from app.core.tenant import registrar_inicializador
from app.core.texto import normalizar_texto
from app.plataforma import politicas as plataforma_politicas


# ---- Catálogo ----


categoria_repo = CategoriaRepository()
temporada_repo = TemporadaRepository()
talla_repo = TallaRepository()
color_repo = ColorRepository()
material_repo = MaterialRepository()
producto_repo = ProductoRepository()
variante_repo = VarianteRepository()
medida_repo = TablaMedidaRepository()

# Datos base de toda empresa (los INSERT de docs/fashionstore_esquema.sql). Una
# sola fuente: la usan el inicializador de empresa nueva y scripts/seed_catalogo.py.
# Colores, categorías y productos no se siembran: los define cada empresa.
# (código, descripción, orden)
TALLAS_BASE: list[tuple[str, str, int]] = [
    ("XS", "Extra small", 1),
    ("S", "Small", 2),
    ("M", "Medium", 3),
    ("L", "Large", 4),
    ("XL", "Extra large", 5),
    ("XXL", "Doble extra large", 6),
]

MATERIALES_BASE: list[str] = [
    "Algodon",
    "Hilo",
    "Poliester",
    "Lino",
    "Mezclilla",
    "Lana",
    "Seda",
    "Cuero sintetico",
]


@registrar_inicializador
def sembrar_catalogos_base(db: Session) -> None:
    """Inicializador de empresa nueva (ver `core.tenant.registrar_inicializador`):
    crea las tallas y los materiales base que falten en la empresa de la sesión.
    Idempotente y sin confirmar: la transacción es de quien registra la empresa."""
    tallas = set(talla_repo.listar_codigos(db))
    for codigo, descripcion, orden in TALLAS_BASE:
        if codigo not in tallas:
            db.add(Talla(codigo=codigo, descripcion=descripcion, orden=orden))
    materiales = set(material_repo.listar_nombres(db))
    for nombre in MATERIALES_BASE:
        if nombre not in materiales:
            db.add(Material(nombre=nombre))
    db.flush()


def imagen_principal_url(producto: Producto) -> str | None:
    if not producto.imagenes:
        return None
    principal = next((img for img in producto.imagenes if img.es_principal), producto.imagenes[0])
    return storage.url_catalogo(principal.url)


def a_item_catalogo(producto: Producto) -> CatalogoItemRespuesta:
    return CatalogoItemRespuesta(
        id=producto.id,
        codigo=producto.codigo,
        nombre=producto.nombre,
        categoria_id=producto.categoria_id,
        genero=producto.genero,
        precio_base=producto.precio_base,
        admite_probador=producto.admite_probador,
        imagen_principal=imagen_principal_url(producto),
    )


def abrir_imagen_valida(contenido: bytes) -> Image.Image:
    """Abre y decodifica `contenido` con Pillow (no confía en la extensión ni
    en el content-type que mandó el cliente). Si no es una imagen real, lanza
    DomainError. Cada llamador conserva su propio límite de tamaño y las
    demás reglas (formato, canal alfa...)."""
    try:
        imagen = Image.open(io.BytesIO(contenido))
        imagen.load()
    except UnidentifiedImageError as exc:
        raise DomainError("El archivo no es una imagen válida") from exc
    return imagen


def obtener_variante(db: Session, variante_id: int) -> ProductoVariante:
    """Para que las secciones de este paquete (Inventario, Probador) y `comercial`
    validen una variante sin consultar producto_variante directamente."""
    return variante_repo.obtener(db, variante_id)


def buscar_variante(db: Session, variante_id: int) -> ProductoVariante | None:
    """Como obtener_variante, pero devuelve la variante aunque esté dada de
    baja (y None si no existe), sin lanzar: para mostrar lo que un cliente
    ya tenía guardado (p. ej. su carrito) aunque ya no se venda."""
    return variante_repo.buscar(db, variante_id)


def obtener_producto(db: Session, producto_id: int) -> Producto:
    """Para que las secciones de este paquete (p. ej. Abastecimiento, para
    producto_proveedor) y `comercial` validen un producto sin consultar la tabla
    `producto` directamente."""
    return producto_repo.obtener(db, producto_id)


def obtener_categoria(db: Session, categoria_id: int) -> Categoria:
    """Para que `comercial` (alcance de una promoción) valide una categoría que
    llega del cliente antes de guardarla como FK, sin consultar la tabla
    `categoria` directamente. 404 si no existe, está inactiva o es de otra
    empresa."""
    return categoria_repo.obtener(db, categoria_id)


def obtener_temporada(db: Session, temporada_id: int) -> Temporada:
    """Como `obtener_categoria`, para la temporada del alcance de una
    promoción."""
    return temporada_repo.obtener(db, temporada_id)


def obtener_talla(db: Session, talla_id: int) -> Talla:
    """Para que las demás secciones de este paquete (p. ej. Probador, para el
    orden de las tallas al recomendar una) resuelvan una talla sin consultar la
    tabla `talla` directamente."""
    return talla_repo.obtener(db, talla_id)


def obtener_tallas(db: Session, talla_ids: Iterable[int]) -> dict[int, Talla]:
    """Como `obtener_talla`, pero para varias tallas en una sola consulta:
    `talla_id` -> Talla. Si alguna no existe, lanza 404 igual que
    `obtener_talla`."""
    ids = set(talla_ids)
    tallas = talla_repo.listar_por_ids(db, ids)
    if len(tallas) != len(ids):
        raise NoEncontradoError("Talla no encontrado")
    return tallas


def listar_medidas_para_variante(db: Session, variante_id: int) -> list[TablaMedida]:
    """Para que la sección Probador cruce las medidas estimadas del cliente con
    tabla_medida sin consultar esa tabla directamente. Prioriza las filas
    específicas del producto de la variante; si no hay ninguna, cae a las
    de su categoría."""
    variante = variante_repo.obtener(db, variante_id)
    medidas = medida_repo.listar_por_producto(db, variante.producto_id)
    if medidas:
        return medidas
    return medida_repo.listar_por_categoria(db, variante.producto.categoria_id)


def obtener_precio_efectivo(variante: ProductoVariante) -> Decimal:
    """Para que `comercial` (ventas) calcule precio_unitario sin reimplementar la regla
    de precio (propio de la variante, o heredado de su producto)."""
    return variante.precio if variante.precio is not None else variante.producto.precio_base


def describir_variante(db: Session, variante: ProductoVariante) -> str:
    """Para que `comercial` nombre una variante en un comprobante o un correo sin consultar `talla` ni `color`:
    "Polera Nike · talla M · Blanco"."""
    talla = talla_repo.obtener(db, variante.talla_id)
    color = color_repo.obtener(db, variante.color_id)
    return f"{variante.producto.nombre} · talla {talla.codigo} · {color.nombre}"


def obtener_info_promocion(variante: ProductoVariante) -> tuple[int, int, int | None]:
    """(producto_id, categoria_id, temporada_id) de una variante, para que
    `comercial` (ventas) busque promociones vigentes (promocion_alcance) sin consultar
    `producto` directamente."""
    producto = variante.producto
    return producto.id, producto.categoria_id, producto.temporada_id


def listar_catalogo_para_paquete(db: Session, desde_id: int, limite: int) -> tuple[list[Producto], int, bool]:
    """Para `sincronizacion` (paquete de descarga offline): una página de productos activos con
    sus variantes activas e imágenes, por clave (`id > desde_id`). Devuelve (productos, total de
    productos activos, hay_mas)."""
    return producto_repo.listar_para_paquete(db, desde_id, limite)


def listar_referencia_para_paquete(db: Session) -> tuple[list[Categoria], list[Talla], list]:
    """Para `sincronizacion`: categorías activas, tallas y colores de la empresa, con los que el
    cliente offline arma los filtros y las etiquetas del catálogo descargado."""
    return categoria_repo.listar_activas(db), talla_repo.listar_todas(db), color_repo.listar_todos(db)


def listar_valores_referencia(db: Session) -> ValoresReferenciaCatalogo:
    """Para que `inteligencia` arme el prompt de Groq con los valores
    válidos reales, sin consultar categoria/material/color/talla/temporada
    directamente."""
    return ValoresReferenciaCatalogo(
        categorias=categoria_repo.listar_nombres_activos(db),
        materiales=material_repo.listar_nombres(db),
        colores=color_repo.listar_nombres(db),
        tallas=talla_repo.listar_codigos(db),
        temporadas=temporada_repo.listar_nombres_vigentes(db),
    )


def resolver_filtros_por_nombre(
    db: Session,
    categoria: str | None,
    material: str | None,
    color: str | None,
    talla: str | None,
    temporada: str | None,
    genero: Genero | None,
    precio_max,
) -> FiltrosCatalogo:
    """Para `inteligencia`: matchea cada nombre que devolvió Groq
    (case-insensitive, exacto) contra la tabla correspondiente. Un nombre
    sin match deja ese filtro en None -- nunca rompe la búsqueda, solo la
    deja sin acotar por ese campo."""
    return FiltrosCatalogo(
        categoria_id=categoria_repo.id_por_nombre(db, categoria),
        material_id=material_repo.id_por_nombre(db, material),
        color_id=color_repo.id_por_nombre(db, color),
        talla_id=talla_repo.id_por_codigo(db, talla),
        temporada_id=temporada_repo.id_por_nombre(db, temporada),
        genero=genero,
        precio_max=precio_max,
    )


def resolver_categoria_por_nombre(db: Session, nombre: str | None) -> int | None:
    """Para `inteligencia` (reporte por voz): matchea el nombre de
    categoría que devolvió Groq sin consultar `categoria` directamente.
    Sin match, devuelve None -- no rompe el reporte."""
    return categoria_repo.id_por_nombre(db, nombre)


def resolver_categorias_por_nombres(db: Session, nombres: list[str]) -> tuple[list[int], list[str]]:
    """Para `inteligencia` (reportes generativos): resuelve nombres de categoría a ids entre las
    categorías ACTIVAS de la empresa de la sesión. Igualdad exacta sobre el texto normalizado
    (sin mayúsculas, tildes ni espacios de más), nunca un patrón. El id es el de esa categoría
    y NADA MÁS: no se incluyen sus subcategorías (decisión de E09). Devuelve (ids sin repetir en
    el orden pedido, nombres sin coincidencia). Los nombres vacíos se ignoran."""
    por_nombre: dict[str, list[int]] = {}
    for categoria_id, nombre in categoria_repo.listar_id_nombre_activas(db):
        por_nombre.setdefault(normalizar_texto(nombre), []).append(categoria_id)
    ids: list[int] = []
    sin_coincidencia: list[str] = []
    for nombre in nombres:
        clave = normalizar_texto(nombre)
        if not clave:
            continue
        encontrados = por_nombre.get(clave)
        if not encontrados:
            sin_coincidencia.append(nombre.strip())
            continue
        ids.extend(i for i in encontrados if i not in ids)
    return ids, sin_coincidencia


def resolver_productos_por_nombres(
    db: Session, nombres: list[str], tope: int = 10
) -> tuple[list[int], list[str], list[str]]:
    """Para `inteligencia` (reportes generativos): resuelve nombres de producto a ids entre los
    productos ACTIVOS de la empresa de la sesión. El nombre pedido debe estar CONTENIDO en el
    del producto, sin distinguir mayúsculas, tildes ni espacios de más (la comparación es en
    Python: el texto nunca arma un patrón LIKE). Un nombre que coincide con más de `tope`
    productos es ambiguo y no se resuelve. Devuelve (ids sin repetir, nombres ambiguos, nombres
    sin coincidencia). Los nombres vacíos se ignoran."""
    productos = [(producto_id, normalizar_texto(nombre)) for producto_id, nombre in producto_repo.listar_id_nombre_activos(db)]
    ids: list[int] = []
    ambiguos: list[str] = []
    sin_coincidencia: list[str] = []
    for nombre in nombres:
        clave = normalizar_texto(nombre)
        if not clave:
            continue
        encontrados = [producto_id for producto_id, nombre_producto in productos if clave in nombre_producto]
        if not encontrados:
            sin_coincidencia.append(nombre.strip())
        elif len(encontrados) > tope:
            ambiguos.append(nombre.strip())
        else:
            ids.extend(i for i in encontrados if i not in ids)
    return ids, ambiguos, sin_coincidencia


def listar_nombres_categorias_activas(db: Session) -> list[str]:
    """Para `inteligencia` (sugerencias cuando un nombre de categoría no coincide): los nombres
    de las categorías activas de la empresa."""
    return categoria_repo.listar_nombres_activos(db)


def reporte_existencias_por_producto(
    db: Session,
    sucursal_ids: list[int] | None,
    categoria_ids: list[int] | None,
    producto_ids: list[int] | None,
    limite: int,
) -> list[dict]:
    """Para `inteligencia` (reportes generativos): los `limite` productos con menos existencia,
    de menor a mayor. Cada fila: `producto_id`, `producto`, `categoria`, `disponible` (suma de
    sus variantes ACTIVAS en las sucursales pedidas; None = todas), `stock_minimo` (la suma de
    sus mínimos) y `bajo_minimo` (disponible <= stock_minimo, el mismo criterio de las alertas
    de inventario aplicado al total). Solo productos activos con alguna fila de stock; las listas
    vacías no coinciden con nada. La categoría filtra por id exacto, sin subcategorías."""
    if limite < 1:
        raise DomainError("El límite debe ser al menos 1.")
    filas = existencias_por_producto(db, sucursal_ids, categoria_ids, producto_ids, limite)
    return [
        {
            "producto_id": fila["producto_id"],
            "producto": fila["producto"],
            "categoria": fila["categoria"],
            "disponible": int(fila["disponible"]),
            "stock_minimo": int(fila["stock_minimo"]),
            "bajo_minimo": int(fila["disponible"]) <= int(fila["stock_minimo"]),
        }
        for fila in filas
    ]


def listar_variantes_temporada_vigente(db: Session) -> set[int]:
    """Para `inteligencia` (capa de reglas del recomendador): variantes
    activas cuyo producto pertenece a una temporada vigente
    (`Temporada.activo`, mismo criterio que `listar_valores_referencia`).
    Un producto sin temporada asignada no cuenta como vigente."""
    return variante_repo.listar_ids_de_temporada_vigente(db)


def listar_variantes_de_producto(db: Session, producto_id: int) -> set[int]:
    """Para `inteligencia`: variantes de un producto, para excluirlo de su
    propio carrusel de recomendaciones (detalle de prenda)."""
    return variante_repo.listar_ids_por_producto(db, producto_id)


def listar_items_por_variantes(db: Session, variante_ids: list[int]) -> dict[int, CatalogoItemRespuesta]:
    """Para `inteligencia`: resuelve cada variante candidata a la tarjeta de
    su producto (imagen, nombre, precio), sin consultar producto_variante/
    producto directamente. Variantes de un mismo producto resuelven al
    mismo `CatalogoItemRespuesta` (mismo `id`) -- el llamador decide si
    colapsarlas."""
    if not variante_ids:
        return {}
    filas = variante_repo.listar_productos_por_variantes(db, variante_ids)
    return {variante_id: a_item_catalogo(producto) for variante_id, producto in filas}


# ---- Inventario ----
# Corazón de la sección Inventario: actualizar_stock_operacion() es la
# operación atómica compartida (kardex + costeo promedio ponderado) que usan
# CU-08 (abastecimiento), CU-09, CU-13 y CU-14 (ventas, en `comercial`) y CU-17 (devolución).
# reservar_stock()/liberar_stock() manejan la cantidad_reservada sin nunca
# generar un movimiento ni tocar cantidad_fisica.
#
# Ninguna de las tres es un caso de uso del catálogo: son la lógica interna
# que evita que cada caso de uso reimplemente el cálculo del promedio
# ponderado o el manejo de reservas.


stock_repo = StockRepository()
movimiento_repo = MovimientoRepository()
tipo_movimiento_repo = TipoMovimientoRepository()

_CUATRO_DECIMALES = Decimal("0.0001")


def bloquear_stock_en_orden(db: Session, claves: Iterable[tuple[int, int]]) -> None:
    """Adquiere de antemano los bloqueos (FOR UPDATE) de las filas de stock
    de un lote de líneas, SIEMPRE en orden ascendente por (variante_id,
    sucursal_id) y sin repetir claves. Es el único punto donde se ordena:
    toda operación que recorre varias líneas tocando stock (recepción,
    transferencia, venta, reserva, anulación...) lo llama una vez antes del
    bucle, y el bucle sigue procesando las líneas en su orden original (las
    respuestas, el detalle y el historial no cambian). Evita el deadlock entre
    dos lotes que traen las mismas variantes en distinto orden.

    Solo bloquea filas que ya existen; las que falten las sigue creando
    `obtener_o_crear_bloqueado` al procesar cada línea (ver T3 del análisis).
    No valida nada: un error de variante o sucursal inexistente lo sigue
    lanzando la línea que lo causa, como antes."""
    ordenadas = sorted(set(claves))
    if ordenadas:
        stock_repo.bloquear_existentes(db, ordenadas)


def actualizar_stock_operacion(
    db: Session,
    *,
    variante_id: int,
    sucursal_id: int,
    tipo_movimiento_codigo: str,
    cantidad: int,
    costo_unitario: Decimal | None = None,
    referencia_tipo: str | None = None,
    referencia_id: int | None = None,
    usuario_id: int | None = None,
    observacion: str | None = None,
    commit: bool = True,
) -> MovimientoInventario:
    """`commit=False` lo usan las operaciones (de este paquete y de `comercial`) que registran
    varios movimientos como una sola transacción (p. ej.
    RegistrarRecepcionMercaderia.registrar con varias líneas, o
    enviar_transferencia/recibir_transferencia de CU-09): si una línea
    falla, ninguna de las anteriores debe quedar aplicada. Quien pasa
    `commit=False` es responsable de hacer `db.commit()` al final."""
    if cantidad <= 0:
        raise DomainError("cantidad debe ser positiva")

    obtener_variante(db, variante_id)  # 404 si no existe
    plataforma_politicas.obtener_sucursal(db, sucursal_id)  # 404 si no existe

    tipo = tipo_movimiento_repo.obtener_por_codigo(db, tipo_movimiento_codigo)

    if tipo.afecta_costo and costo_unitario is None:
        raise DomainError(f"El tipo de movimiento '{tipo.codigo}' requiere costo_unitario")

    # Bloquea la fila de stock (SELECT FOR UPDATE en Postgres) para que dos
    # movimientos concurrentes sobre la misma variante+sucursal no pisen el
    # saldo el uno al otro.
    stock = stock_repo.obtener_o_crear_bloqueado(db, variante_id, sucursal_id)

    cantidad_firmada = cantidad * tipo.signo
    stock_anterior = stock.cantidad_fisica
    nueva_cantidad_fisica = stock_anterior + cantidad_firmada

    if nueva_cantidad_fisica < 0:
        raise ConflictoError("El movimiento dejaría el stock físico en negativo")
    if nueva_cantidad_fisica < stock.cantidad_reservada:
        raise ConflictoError("El movimiento dejaría stock reservado sin respaldo físico")

    # Si el tipo afecta el costo (siempre una entrada: no tiene sentido
    # recalcular el promedio con una salida), recalcula el promedio
    # ponderado con la cantidad y el costo de ESTE ingreso.
    if tipo.afecta_costo and tipo.signo > 0:
        costo_anterior = stock.costo_promedio
        promedio_exacto = (
            Decimal(stock_anterior) * costo_anterior + Decimal(cantidad) * costo_unitario
        ) / Decimal(stock_anterior + cantidad)
        # NUMERIC(12,4) en la base: se redondea acá para que el valor que
        # ve el código sea el mismo que va a quedar persistido.
        nuevo_promedio = promedio_exacto.quantize(_CUATRO_DECIMALES, rounding=ROUND_HALF_UP)
    else:
        nuevo_promedio = stock.costo_promedio

    # Actualiza stock.cantidad_fisica y costo_promedio.
    stock.cantidad_fisica = nueva_cantidad_fisica
    stock.costo_promedio = nuevo_promedio

    # Inserta el movimiento con su saldo_post y costo_promedio_post.
    movimiento = MovimientoInventario(
        variante_id=variante_id,
        sucursal_id=sucursal_id,
        tipo_movimiento_id=tipo.id,
        cantidad=cantidad_firmada,
        costo_unitario=costo_unitario,
        costo_promedio_post=nuevo_promedio if tipo.afecta_costo else None,
        saldo_post=nueva_cantidad_fisica,
        referencia_tipo=referencia_tipo,
        referencia_id=referencia_id,
        usuario_id=usuario_id,
        observacion=observacion,
    )
    movimiento_repo.crear(db, movimiento)

    if commit:
        db.commit()
    else:
        db.flush()
    db.refresh(movimiento)
    return movimiento


def reservar_stock(
    db: Session, variante_id: int, sucursal_id: int, cantidad: int, commit: bool = True
) -> Stock:
    """Incrementa cantidad_reservada. Nunca toca cantidad_fisica ni genera
    movimiento de inventario. `commit=False`: ver el comentario en
    actualizar_stock_operacion (lo usa reservas.CU-12, que reserva varias
    líneas como una sola transacción)."""
    if cantidad <= 0:
        raise DomainError("cantidad debe ser positiva")

    obtener_variante(db, variante_id)
    plataforma_politicas.obtener_sucursal(db, sucursal_id)

    # La fila llega bloqueada (SELECT FOR UPDATE) desde acá: si dos clientes
    # reservan la misma variante+sucursal al mismo tiempo, el segundo espera
    # a que el primero confirme y recién ahí lee el saldo ya actualizado, en
    # vez de que ambos lean "disponible" antes de que el otro reserve.
    stock = stock_repo.obtener_o_crear_bloqueado(db, variante_id, sucursal_id)
    disponible = stock.cantidad_fisica - stock.cantidad_reservada
    if cantidad > disponible:
        raise StockInsuficienteError(
            "No hay stock disponible suficiente para reservar",
            variante_id=variante_id,
            solicitado=cantidad,
            disponible=max(disponible, 0),
        )

    stock.cantidad_reservada += cantidad
    if commit:
        db.commit()
    else:
        db.flush()
    db.refresh(stock)
    return stock


def liberar_stock(
    db: Session, variante_id: int, sucursal_id: int, cantidad: int, commit: bool = True
) -> Stock:
    """Decrementa cantidad_reservada. Nunca toca cantidad_fisica ni genera
    movimiento de inventario. `commit=False`: ver el comentario en
    actualizar_stock_operacion."""
    if cantidad <= 0:
        raise DomainError("cantidad debe ser positiva")

    stock = stock_repo.obtener_o_crear_bloqueado(db, variante_id, sucursal_id)
    if cantidad > stock.cantidad_reservada:
        raise ConflictoError("No se puede liberar más de lo reservado")

    stock.cantidad_reservada -= cantidad
    if commit:
        db.commit()
    else:
        db.flush()
    db.refresh(stock)
    return stock


def obtener_stock(db: Session, variante_id: int, sucursal_id: int) -> Stock:
    """Para que `comercial` (ventas) lea el costo_promedio actual antes de congelarlo en
    el detalle de la venta, sin consultar `stock` directamente."""
    stock = stock_repo.obtener_por_variante_sucursal(db, variante_id, sucursal_id)
    if stock is None:
        raise NoEncontradoError("Todavía no hay stock registrado para esa variante en esa sucursal")
    return stock


def listar_stock_para_paquete(
    db: Session, sucursal_id: int, desde, desde_variante_id: int, limite: int
) -> tuple[list[Stock], bool]:
    """Para `sincronizacion` (paquete de descarga offline): una página del stock de una sucursal
    (solo variantes activas), por clave (`variante_id > desde_variante_id`). Con `desde` solo las
    filas modificadas desde ese instante. Devuelve (filas, hay_mas)."""
    return stock_repo.listar_para_paquete(db, sucursal_id, desde, desde_variante_id, limite)


def listar_variantes_con_stock(db: Session, sucursal_id: int | None = None) -> set[int]:
    """Para `inteligencia` (capa de reglas del recomendador) y `catalogo`
    (CU-06, filtro `solo_disponibles`): variantes con stock disponible, en
    cualquier sucursal si no se pasa `sucursal_id` o en esa sola si se
    pasa, sin consultar `stock` directamente."""
    return stock_repo.listar_variantes_con_stock(db, sucursal_id)


# ---- Probador ----
# Funciones de la sección Probador que usa `inteligencia` (recomendador y
# reportes), sin ser casos de uso del catálogo: son consultas sobre la tabla de
# generaciones, para que nadie más tenga que tocarla directamente.


generacion_repo = GeneracionRepository()


def listar_generaciones_recientes_cliente(db: Session, cliente_id: int, limite: int = 50) -> list[ProbadorGeneracion]:
    """Para `inteligencia` (capa de reglas del recomendador): usos recientes
    del probador de un cliente, sin consultar `probador_generacion`
    directamente."""
    return generacion_repo.listar_reciente_por_cliente(db, cliente_id, limite)


def reporte_uso_probador(db: Session, periodo: ParametrosPeriodo) -> list[dict]:
    """Para `inteligencia` (reportes): generaciones del probador por estado en el período."""
    return generacion_repo.contar_por_periodo(db, periodo.desde, periodo.hasta)
