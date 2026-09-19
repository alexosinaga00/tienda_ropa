"""CU-09 — Consultar catálogo

Actor: Cliente.
Precondición: ninguna (accesible sin sesión).
Postcondición: el cliente visualiza el catálogo de productos disponibles.

Caso de uso COMPUESTO: incluye también el detalle de una prenda y el
lookup de imágenes que usa el dashboard del back office (antes "consultar
detalle de prenda" era un CU aparte; el catálogo de 43 lo funde acá).
"""

from sqlalchemy.orm import Session

from app.core.deps import ParametrosPaginacion
from app.catalogo.politicas import a_item_catalogo, imagen_principal_url
from app.catalogo.repository import ProductoRepository, VarianteRepository
from app.catalogo.schemas import (
    CatalogoDetalleRespuesta,
    CatalogoItemRespuesta,
    ImagenRespuesta,
    ProductoImagenLookupItem,
    VarianteCatalogoRespuesta,
)
from app.core import storage
from app.inventario.casos_uso.cu13_consultar_disponibilidad_sucursal import ConsultarDisponibilidadSucursal


class ConsultarCatalogo:
    def __init__(self) -> None:
        self._productos = ProductoRepository()
        self._variantes = VarianteRepository()
        self._disponibilidad = ConsultarDisponibilidadSucursal()

    def listar(self, db: Session, paginacion: ParametrosPaginacion) -> list[CatalogoItemRespuesta]:
        productos = self._productos.listar_publico(db, paginacion)
        return [a_item_catalogo(p) for p in productos]

    def _disponibilidad_variante(self, db: Session, variante_id: int, sucursal_id: int | None) -> int:
        """Sin `sucursal_id`, "disponible" es la suma entre todas las
        sucursales (mismo criterio que usa `inteligencia` para decidir si
        una variante tiene stock); con `sucursal_id`, la de esa sucursal
        sola. Nunca None: sin stock registrado es 0, no una ausencia de dato
        (CU-13 ya no distingue ambos casos)."""
        stocks = self._disponibilidad.ejecutar(db, variante_id, sucursal_id)
        return sum(s.cantidad_disponible for s in stocks)

    def obtener_detalle(
        self, db: Session, producto_id: int, sucursal_id: int | None = None
    ) -> CatalogoDetalleRespuesta:
        producto = self._productos.obtener_publico_detalle(db, producto_id)

        variantes = [
            VarianteCatalogoRespuesta(
                id=v.id,
                talla_id=v.talla_id,
                color_id=v.color_id,
                sku=v.sku,
                precio_efectivo=v.precio if v.precio is not None else producto.precio_base,
                cantidad_disponible=self._disponibilidad_variante(db, v.id, sucursal_id),
            )
            for v in producto.variantes
            if v.activo
        ]
        imagenes = [ImagenRespuesta.from_modelo(img, storage.url_catalogo(img.url)) for img in producto.imagenes]

        return CatalogoDetalleRespuesta(
            id=producto.id,
            codigo=producto.codigo,
            nombre=producto.nombre,
            descripcion=producto.descripcion,
            categoria_id=producto.categoria_id,
            material_id=producto.material_id,
            temporada_id=producto.temporada_id,
            coleccion_id=producto.coleccion_id,
            genero=producto.genero,
            precio_base=producto.precio_base,
            admite_probador=producto.admite_probador,
            variantes=variantes,
            imagenes=imagenes,
        )

    def resolver_imagen_lookup(
        self, db: Session, variante_ids: list[int] | None, producto_ids: list[int] | None
    ) -> list[ProductoImagenLookupItem]:
        """Resuelve nombre+foto en lote para el dashboard del back office.
        No filtra por `activo`: quien llama ya conoce estos ids por una
        venta o una alerta de stock real, así que interesa mostrar la
        prenda aunque haya quedado inactiva después."""
        resultados: list[ProductoImagenLookupItem] = []
        if variante_ids:
            for variante, producto, talla, color in self._variantes.listar_para_detalle_publico(db, variante_ids):
                resultados.append(
                    ProductoImagenLookupItem(
                        variante_id=variante.id,
                        producto_id=producto.id,
                        producto_nombre=producto.nombre,
                        imagen_principal=imagen_principal_url(producto),
                        talla_codigo=talla.codigo,
                        color_nombre=color.nombre,
                    )
                )
        if producto_ids:
            for producto in self._productos.listar_por_ids_publico(db, producto_ids):
                resultados.append(
                    ProductoImagenLookupItem(
                        producto_id=producto.id,
                        producto_nombre=producto.nombre,
                        imagen_principal=imagen_principal_url(producto),
                    )
                )
        return resultados
