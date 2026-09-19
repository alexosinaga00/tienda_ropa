"""Funciones que catalogo expone para otros paquetes, sin ser casos de uso
del catálogo: son consultas sobre las tablas de este paquete (producto,
variante, talla, tabla_medida), para que nadie más tenga que tocarlas
directamente."""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.catalogo.models import (
    Categoria,
    Color,
    Material,
    Producto,
    ProductoVariante,
    Talla,
    TablaMedida,
    Temporada,
)
from app.catalogo.repository import (
    CategoriaRepository,
    ColorRepository,
    MaterialRepository,
    ProductoRepository,
    TablaMedidaRepository,
    TallaRepository,
    TemporadaRepository,
    VarianteRepository,
)
from app.catalogo.schemas import CatalogoItemRespuesta, FiltrosCatalogo, Genero, ValoresReferenciaCatalogo
from app.core import storage

categoria_repo = CategoriaRepository()
temporada_repo = TemporadaRepository()
talla_repo = TallaRepository()
color_repo = ColorRepository()
material_repo = MaterialRepository()
producto_repo = ProductoRepository()
variante_repo = VarianteRepository()
medida_repo = TablaMedidaRepository()


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


def obtener_variante(db: Session, variante_id: int) -> ProductoVariante:
    """Para que otros paquetes (p. ej. `probador`, `inventario`) validen una
    variante sin consultar producto_variante directamente."""
    return variante_repo.obtener(db, variante_id)


def buscar_variante(db: Session, variante_id: int) -> ProductoVariante | None:
    """Como obtener_variante, pero devuelve la variante aunque esté dada de
    baja (y None si no existe), sin lanzar: para mostrar lo que un cliente
    ya tenía guardado (p. ej. su carrito) aunque ya no se venda."""
    return variante_repo.buscar(db, variante_id)


def obtener_producto(db: Session, producto_id: int) -> Producto:
    """Para que otros paquetes (p. ej. `abastecimiento`, para
    producto_proveedor) validen un producto sin consultar la tabla
    `producto` directamente."""
    return producto_repo.obtener(db, producto_id)


def obtener_talla(db: Session, talla_id: int) -> Talla:
    """Para que otros paquetes (p. ej. `probador`, para el orden de las
    tallas al recomendar una) resuelvan una talla sin consultar la tabla
    `talla` directamente."""
    return talla_repo.obtener(db, talla_id)


def listar_medidas_para_variante(db: Session, variante_id: int) -> list[TablaMedida]:
    """Para que `probador` cruce las medidas estimadas del cliente con
    tabla_medida sin consultar esa tabla directamente. Prioriza las filas
    específicas del producto de la variante; si no hay ninguna, cae a las
    de su categoría."""
    variante = variante_repo.obtener(db, variante_id)
    medidas = medida_repo.listar_por_producto(db, variante.producto_id)
    if medidas:
        return medidas
    return medida_repo.listar_por_categoria(db, variante.producto.categoria_id)


def obtener_precio_efectivo(variante: ProductoVariante) -> Decimal:
    """Para que `ventas` calcule precio_unitario sin reimplementar la regla
    de precio (propio de la variante, o heredado de su producto)."""
    return variante.precio if variante.precio is not None else variante.producto.precio_base


def obtener_info_promocion(variante: ProductoVariante) -> tuple[int, int, int | None]:
    """(producto_id, categoria_id, temporada_id) de una variante, para que
    `ventas` busque promociones vigentes (promocion_alcance) sin consultar
    `producto` directamente."""
    producto = variante.producto
    return producto.id, producto.categoria_id, producto.temporada_id


def listar_valores_referencia(db: Session) -> ValoresReferenciaCatalogo:
    """Para que `inteligencia` arme el prompt de Groq con los valores
    válidos reales, sin consultar categoria/material/color/talla/temporada
    directamente."""
    return ValoresReferenciaCatalogo(
        categorias=list(db.scalars(select(Categoria.nombre).where(Categoria.activo.is_(True)))),
        materiales=list(db.scalars(select(Material.nombre))),
        colores=list(db.scalars(select(Color.nombre))),
        tallas=list(db.scalars(select(Talla.codigo))),
        temporadas=list(
            db.scalars(select(Temporada.nombre).where(Temporada.activo.is_(True)).distinct())
        ),
    )


def _resolver_por_nombre(db: Session, columna_id, columna_nombre, nombre: str | None) -> int | None:
    if not nombre:
        return None
    return db.scalar(select(columna_id).where(columna_nombre.ilike(nombre)))


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
        categoria_id=_resolver_por_nombre(db, Categoria.id, Categoria.nombre, categoria),
        material_id=_resolver_por_nombre(db, Material.id, Material.nombre, material),
        color_id=_resolver_por_nombre(db, Color.id, Color.nombre, color),
        talla_id=_resolver_por_nombre(db, Talla.id, Talla.codigo, talla),
        temporada_id=_resolver_por_nombre(db, Temporada.id, Temporada.nombre, temporada),
        genero=genero,
        precio_max=precio_max,
    )


def resolver_categoria_por_nombre(db: Session, nombre: str | None) -> int | None:
    """Para `inteligencia` (reporte por voz): matchea el nombre de
    categoría que devolvió Groq sin consultar `categoria` directamente.
    Sin match, devuelve None -- no rompe el reporte."""
    return _resolver_por_nombre(db, Categoria.id, Categoria.nombre, nombre)


def listar_variantes_temporada_vigente(db: Session) -> set[int]:
    """Para `inteligencia` (capa de reglas del recomendador): variantes
    activas cuyo producto pertenece a una temporada vigente
    (`Temporada.activo`, mismo criterio que `listar_valores_referencia`).
    Un producto sin temporada asignada no cuenta como vigente."""
    filas = db.scalars(
        select(ProductoVariante.id)
        .join(Producto, Producto.id == ProductoVariante.producto_id)
        .join(Temporada, Temporada.id == Producto.temporada_id)
        .where(ProductoVariante.activo.is_(True), Producto.activo.is_(True), Temporada.activo.is_(True))
    )
    return set(filas)


def listar_variantes_de_producto(db: Session, producto_id: int) -> set[int]:
    """Para `inteligencia`: variantes de un producto, para excluirlo de su
    propio carrusel de recomendaciones (detalle de prenda)."""
    return set(db.scalars(select(ProductoVariante.id).where(ProductoVariante.producto_id == producto_id)))


def listar_items_por_variantes(db: Session, variante_ids: list[int]) -> dict[int, CatalogoItemRespuesta]:
    """Para `inteligencia`: resuelve cada variante candidata a la tarjeta de
    su producto (imagen, nombre, precio), sin consultar producto_variante/
    producto directamente. Variantes de un mismo producto resuelven al
    mismo `CatalogoItemRespuesta` (mismo `id`) -- el llamador decide si
    colapsarlas."""
    if not variante_ids:
        return {}
    filas = db.execute(
        select(ProductoVariante.id, Producto)
        .join(Producto, Producto.id == ProductoVariante.producto_id)
        .where(ProductoVariante.id.in_(variante_ids))
    ).all()
    return {variante_id: a_item_catalogo(producto) for variante_id, producto in filas}
