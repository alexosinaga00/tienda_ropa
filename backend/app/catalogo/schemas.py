from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# ---- Categoría ------------------------------------------------------------


class CategoriaCrear(BaseModel):
    nombre: str = Field(max_length=60)
    descripcion: str | None = Field(default=None, max_length=200)
    categoria_padre_id: int | None = None


class CategoriaActualizar(BaseModel):
    nombre: str | None = Field(default=None, max_length=60)
    descripcion: str | None = Field(default=None, max_length=200)
    categoria_padre_id: int | None = None


class CategoriaRespuesta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    categoria_padre_id: int | None = None
    nombre: str
    descripcion: str | None = None
    activo: bool


# ---- Talla -----------------------------------------------------------------


class TallaCrear(BaseModel):
    codigo: str = Field(max_length=10)
    descripcion: str | None = Field(default=None, max_length=40)
    orden: int = 0


class TallaActualizar(BaseModel):
    codigo: str | None = Field(default=None, max_length=10)
    descripcion: str | None = Field(default=None, max_length=40)
    orden: int | None = None


class TallaRespuesta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    codigo: str
    descripcion: str | None = None
    orden: int


# ---- Color -----------------------------------------------------------------


class ColorCrear(BaseModel):
    nombre: str = Field(max_length=40)
    codigo_hex: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")


class ColorActualizar(BaseModel):
    nombre: str | None = Field(default=None, max_length=40)
    codigo_hex: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")


class ColorRespuesta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str
    codigo_hex: str | None = None


# ---- Material ----------------------------------------------------------------


class MaterialCrear(BaseModel):
    nombre: str = Field(max_length=40)
    descripcion: str | None = Field(default=None, max_length=200)


class MaterialActualizar(BaseModel):
    nombre: str | None = Field(default=None, max_length=40)
    descripcion: str | None = Field(default=None, max_length=200)


class MaterialRespuesta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str
    descripcion: str | None = None


# ---- Temporada ---------------------------------------------------------------


class TemporadaCrear(BaseModel):
    nombre: str = Field(max_length=60)
    anio: int = Field(ge=2000, le=2100)
    fecha_inicio: dt.date | None = None
    fecha_fin: dt.date | None = None

    @model_validator(mode="after")
    def _validar_rango(self) -> "TemporadaCrear":
        if self.fecha_inicio and self.fecha_fin and self.fecha_fin <= self.fecha_inicio:
            raise ValueError("fecha_fin debe ser posterior a fecha_inicio")
        return self


class TemporadaActualizar(BaseModel):
    nombre: str | None = Field(default=None, max_length=60)
    anio: int | None = Field(default=None, ge=2000, le=2100)
    fecha_inicio: dt.date | None = None
    fecha_fin: dt.date | None = None
    activo: bool | None = None

    @model_validator(mode="after")
    def _validar_rango(self) -> "TemporadaActualizar":
        if self.fecha_inicio and self.fecha_fin and self.fecha_fin <= self.fecha_inicio:
            raise ValueError("fecha_fin debe ser posterior a fecha_inicio")
        return self


class TemporadaRespuesta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str
    anio: int
    fecha_inicio: dt.date | None = None
    fecha_fin: dt.date | None = None
    activo: bool


# ---- Colección ---------------------------------------------------------------


class ColeccionCrear(BaseModel):
    temporada_id: int | None = None
    nombre: str = Field(max_length=80)
    descripcion: str | None = Field(default=None, max_length=300)


class ColeccionActualizar(BaseModel):
    temporada_id: int | None = None
    nombre: str | None = Field(default=None, max_length=80)
    descripcion: str | None = Field(default=None, max_length=300)
    activo: bool | None = None


class ColeccionRespuesta(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    temporada_id: int | None = None
    nombre: str
    descripcion: str | None = None
    activo: bool


Genero = Literal["hombre", "mujer", "unisex", "nino"]

# ---- Producto ---------------------------------------------------------------


class ProductoCrear(BaseModel):
    codigo: str = Field(max_length=30)
    nombre: str = Field(max_length=120)
    descripcion: str | None = None
    categoria_id: int
    material_id: int | None = None
    temporada_id: int | None = None
    coleccion_id: int | None = None
    genero: Genero = "unisex"
    precio_base: Decimal = Field(ge=0)
    admite_probador: bool = False
    tallas_ids: list[int] = Field(min_length=1)
    colores_ids: list[int] = Field(min_length=1)


class ProductoActualizar(BaseModel):
    codigo: str | None = Field(default=None, max_length=30)
    nombre: str | None = Field(default=None, max_length=120)
    descripcion: str | None = None
    categoria_id: int | None = None
    material_id: int | None = None
    temporada_id: int | None = None
    coleccion_id: int | None = None
    genero: Genero | None = None
    precio_base: Decimal | None = Field(default=None, ge=0)
    admite_probador: bool | None = None
    activo: bool | None = None


class ProductoRespuesta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    codigo: str
    nombre: str
    descripcion: str | None = None
    categoria_id: int
    material_id: int | None = None
    temporada_id: int | None = None
    coleccion_id: int | None = None
    genero: str
    precio_base: Decimal
    admite_probador: bool
    activo: bool
    creado_en: dt.datetime
    creado_por: int | None = None


# ---- Variantes ---------------------------------------------------------------


class VariantesGenerarRequest(BaseModel):
    """Agrega nuevas tallas/colores a un producto ya creado. La
    combinatoria que ya existe no se toca ni se duplica."""

    tallas_ids: list[int] = Field(min_length=1)
    colores_ids: list[int] = Field(min_length=1)


class VarianteActualizar(BaseModel):
    precio: Decimal | None = Field(default=None, ge=0)
    codigo_barras: str | None = Field(default=None, max_length=40)
    activo: bool | None = None


class VarianteRespuesta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    producto_id: int
    talla_id: int
    color_id: int
    sku: str
    codigo_barras: str | None = None
    precio: Decimal | None = None
    precio_efectivo: Decimal
    activo: bool

    @classmethod
    def from_modelo(cls, variante) -> "VarianteRespuesta":
        return cls(
            id=variante.id,
            producto_id=variante.producto_id,
            talla_id=variante.talla_id,
            color_id=variante.color_id,
            sku=variante.sku,
            codigo_barras=variante.codigo_barras,
            precio=variante.precio,
            precio_efectivo=variante.precio if variante.precio is not None else variante.producto.precio_base,
            activo=variante.activo,
        )


class VarianteBusquedaRespuesta(BaseModel):
    """Fila de GET /catalogo/variantes/buscar (POS): una variante con lo
    mínimo que la caja necesita mostrar y mandar en el detalle de la venta,
    sin que el cajero (sin catalogo.gestionar) tenga que pasar por
    /productos/{id}/variantes."""

    variante_id: int
    producto_id: int
    producto_nombre: str
    producto_codigo: str
    talla_codigo: str
    color_nombre: str
    sku: str
    codigo_barras: str | None = None
    precio_efectivo: Decimal


# ---- Tabla de medidas ---------------------------------------------------------


class TablaMedidaCrear(BaseModel):
    talla_id: int
    pecho_min_cm: Decimal | None = None
    pecho_max_cm: Decimal | None = None
    cintura_min_cm: Decimal | None = None
    cintura_max_cm: Decimal | None = None
    hombros_cm: Decimal | None = None
    largo_cm: Decimal | None = None


class TablaMedidaActualizar(BaseModel):
    talla_id: int | None = None
    pecho_min_cm: Decimal | None = None
    pecho_max_cm: Decimal | None = None
    cintura_min_cm: Decimal | None = None
    cintura_max_cm: Decimal | None = None
    hombros_cm: Decimal | None = None
    largo_cm: Decimal | None = None


class TablaMedidaRespuesta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    producto_id: int | None = None
    categoria_id: int | None = None
    talla_id: int
    pecho_min_cm: Decimal | None = None
    pecho_max_cm: Decimal | None = None
    cintura_min_cm: Decimal | None = None
    cintura_max_cm: Decimal | None = None
    hombros_cm: Decimal | None = None
    largo_cm: Decimal | None = None


# ---- Imágenes de producto ------------------------------------------------------


class ImagenRespuesta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    producto_id: int
    color_id: int | None = None
    public_id: str
    url: str
    orden: int
    es_principal: bool

    @classmethod
    def from_modelo(cls, imagen, url: str) -> "ImagenRespuesta":
        return cls(
            id=imagen.id,
            producto_id=imagen.producto_id,
            color_id=imagen.color_id,
            public_id=imagen.url,
            url=url,
            orden=imagen.orden,
            es_principal=imagen.es_principal,
        )


# ---- Catálogo público ----------------------------------------------------------


class FiltrosCatalogo(BaseModel):
    """DTO interno para /catalogo/buscar. No es un body: se arma en el
    router a partir de query params."""

    texto: str | None = None
    categoria_id: int | None = None
    talla_id: int | None = None
    color_id: int | None = None
    material_id: int | None = None
    temporada_id: int | None = None
    genero: Genero | None = None
    precio_min: Decimal | None = None
    precio_max: Decimal | None = None
    # `sucursal_id` no filtra el listado por sí solo (todo producto se
    # vende en todas las sucursales, solo cambia el stock): únicamente
    # acota a esa sucursal el chequeo de `solo_disponibles`. Sin
    # `sucursal_id`, "disponible" es "en alguna sucursal".
    sucursal_id: int | None = None
    solo_disponibles: bool = False


class ValoresReferenciaCatalogo(BaseModel):
    """Nombres activos de las tablas de referencia del catálogo, para que
    `inteligencia` arme el prompt de Groq (P6.1) sin consultar `categoria`,
    `material`, `color`, `talla` ni `temporada` directamente."""

    categorias: list[str]
    materiales: list[str]
    colores: list[str]
    tallas: list[str]
    temporadas: list[str]


class CatalogoItemRespuesta(BaseModel):
    """Fila liviana para el listado. Sin variantes ni medidas: eso es
    solo para el detalle, para no pagar el peso de todo el producto en
    cada fila de una grilla de 50."""

    id: int
    codigo: str
    nombre: str
    categoria_id: int
    genero: str
    precio_base: Decimal
    admite_probador: bool
    imagen_principal: str | None = None


class VarianteCatalogoRespuesta(BaseModel):
    id: int
    talla_id: int
    color_id: int
    sku: str
    precio_efectivo: Decimal
    # Suma entre todas las sucursales si el detalle se pidió sin
    # `sucursal_id`, o la de esa sucursal sola si se pidió (ver
    # ConsultarCatalogo._disponibilidad_variante en cu09_consultar_catalogo.py,
    # que llama a inventario.casos_uso.cu13, nunca a la tabla `stock`
    # directamente).
    cantidad_disponible: int = 0


class ProductoImagenLookupItem(BaseModel):
    """Fila de GET /catalogo/variantes/detalle: resuelve nombre+foto de
    producto en lote, a partir de variante_id o de producto_id. La usa el
    dashboard del back office para mostrar la prenda real en 'se vendió
    hoy' (por variante_id, ya que una Venta solo trae eso) y en 'stock
    bajo' (por producto_id, ya conocido vía inventario/alertas); también
    la usa el carrito de compra de la app Flutter (por variante_id, con
    talla_codigo/color_nombre para mostrar la línea completa)."""

    variante_id: int | None = None
    producto_id: int
    producto_nombre: str
    imagen_principal: str | None = None
    talla_codigo: str | None = None
    color_nombre: str | None = None


class CatalogoDetalleRespuesta(BaseModel):
    id: int
    codigo: str
    nombre: str
    descripcion: str | None = None
    categoria_id: int
    material_id: int | None = None
    temporada_id: int | None = None
    coleccion_id: int | None = None
    genero: str
    precio_base: Decimal
    admite_probador: bool
    variantes: list[VarianteCatalogoRespuesta]
    imagenes: list[ImagenRespuesta]


# ---- Favoritos ---------------------------------------------------------------


class FavoritoCrear(BaseModel):
    variante_id: int


class FavoritoRespuesta(BaseModel):
    variante_id: int
    producto_id: int
    nombre_producto: str
    sku: str
    creado_en: dt.datetime

    @classmethod
    def from_modelo(cls, favorito) -> "FavoritoRespuesta":
        return cls(
            variante_id=favorito.variante_id,
            producto_id=favorito.variante.producto_id,
            nombre_producto=favorito.variante.producto.nombre,
            sku=favorito.variante.sku,
            creado_en=favorito.creado_en,
        )
