from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.crud_base import CRUDBase, CRUDBaseSinActivo
from app.core.deps import ParametrosPaginacion
from app.core.exceptions import ConflictoError, NoEncontradoError
from app.catalogo.models import (
    Categoria,
    Coleccion,
    Color,
    Favorito,
    Material,
    Producto,
    ProductoImagen,
    ProductoVariante,
    Talla,
    TablaMedida,
    Temporada,
)
from app.catalogo.schemas import (
    CategoriaActualizar,
    CategoriaCrear,
    ColeccionActualizar,
    ColeccionCrear,
    ColorActualizar,
    ColorCrear,
    FiltrosCatalogo,
    MaterialActualizar,
    MaterialCrear,
    ProductoActualizar,
    ProductoCrear,
    TablaMedidaActualizar,
    TablaMedidaCrear,
    TallaActualizar,
    TallaCrear,
    TemporadaActualizar,
    TemporadaCrear,
    VarianteActualizar,
)


class CategoriaRepository(CRUDBase[Categoria, CategoriaCrear, CategoriaActualizar]):
    def __init__(self) -> None:
        super().__init__(Categoria)

    def listar_hijos(self, db: Session, categoria_id: int) -> list[Categoria]:
        return list(
            db.scalars(
                select(Categoria).where(
                    Categoria.categoria_padre_id == categoria_id, Categoria.activo.is_(True)
                )
            )
        )


class TallaRepository(CRUDBaseSinActivo[Talla, TallaCrear, TallaActualizar]):
    def __init__(self) -> None:
        super().__init__(Talla)

    def listar(self, db, paginacion, filtros=None):
        consulta = select(Talla).order_by(Talla.orden).offset(paginacion.offset).limit(paginacion.tamanio)
        return list(db.scalars(consulta).all())

    def obtener_por_codigo(self, db: Session, codigo: str) -> Talla | None:
        return db.scalar(select(Talla).where(Talla.codigo == codigo))

    def crear(self, db: Session, datos: TallaCrear) -> Talla:
        if self.obtener_por_codigo(db, datos.codigo) is not None:
            raise ConflictoError("Ya existe una talla con ese código")
        return super().crear(db, datos)

    def actualizar(self, db: Session, id_: int, datos: TallaActualizar) -> Talla:
        if datos.codigo is not None:
            existente = self.obtener_por_codigo(db, datos.codigo)
            if existente is not None and existente.id != id_:
                raise ConflictoError("Ya existe una talla con ese código")
        return super().actualizar(db, id_, datos)


class ColorRepository(CRUDBaseSinActivo[Color, ColorCrear, ColorActualizar]):
    def __init__(self) -> None:
        super().__init__(Color)


class MaterialRepository(CRUDBaseSinActivo[Material, MaterialCrear, MaterialActualizar]):
    def __init__(self) -> None:
        super().__init__(Material)


class TemporadaRepository(CRUDBase[Temporada, TemporadaCrear, TemporadaActualizar]):
    def __init__(self) -> None:
        super().__init__(Temporada)

    def _existe_duplicada(self, db: Session, nombre: str, anio: int, excluir_id: int | None = None) -> bool:
        consulta = select(Temporada).where(Temporada.nombre == nombre, Temporada.anio == anio)
        if excluir_id is not None:
            consulta = consulta.where(Temporada.id != excluir_id)
        return db.scalar(consulta) is not None

    def crear(self, db: Session, datos: TemporadaCrear) -> Temporada:
        if self._existe_duplicada(db, datos.nombre, datos.anio):
            raise ConflictoError("Ya existe una temporada con ese nombre y año")
        return super().crear(db, datos)

    def actualizar(self, db: Session, id_: int, datos: TemporadaActualizar) -> Temporada:
        if datos.nombre is not None or datos.anio is not None:
            actual = self.obtener(db, id_)
            nombre = datos.nombre if datos.nombre is not None else actual.nombre
            anio = datos.anio if datos.anio is not None else actual.anio
            if self._existe_duplicada(db, nombre, anio, excluir_id=id_):
                raise ConflictoError("Ya existe una temporada con ese nombre y año")
        return super().actualizar(db, id_, datos)


class ColeccionRepository(CRUDBase[Coleccion, ColeccionCrear, ColeccionActualizar]):
    def __init__(self) -> None:
        super().__init__(Coleccion)


class ProductoRepository(CRUDBase[Producto, ProductoCrear, ProductoActualizar]):
    def __init__(self) -> None:
        super().__init__(Producto)

    def obtener_por_codigo(self, db: Session, codigo: str) -> Producto | None:
        return db.scalar(select(Producto).where(Producto.codigo == codigo))

    def crear(self, db: Session, datos: ProductoCrear, creado_por: int | None) -> Producto:
        # ProductoCrear trae tallas_ids/colores_ids para la combinatoria de
        # variantes (los resuelve el service); acá solo se persiste la fila
        # de producto en sí.
        campos = datos.model_dump(exclude={"tallas_ids", "colores_ids"})
        existente = self.obtener_por_codigo(db, datos.codigo)
        if existente is not None:
            if existente.activo:
                raise ConflictoError("Ya existe un producto con ese código")
            for campo, valor in campos.items():
                setattr(existente, campo, valor)
            existente.activo = True
            db.commit()
            db.refresh(existente)
            return existente
        producto = Producto(**campos, creado_por=creado_por)
        db.add(producto)
        db.commit()
        db.refresh(producto)
        return producto

    def listar_publico(self, db: Session, paginacion: ParametrosPaginacion) -> list[Producto]:
        consulta = (
            select(Producto)
            .where(Producto.activo.is_(True))
            .options(selectinload(Producto.imagenes))
            .order_by(Producto.id)
            .offset(paginacion.offset)
            .limit(paginacion.tamanio)
        )
        return list(db.scalars(consulta).all())

    def buscar_publico(
        self, db: Session, paginacion: ParametrosPaginacion, filtros: FiltrosCatalogo
    ) -> list[Producto]:
        consulta = select(Producto).where(Producto.activo.is_(True)).options(selectinload(Producto.imagenes))

        if filtros.texto:
            patron = f"%{filtros.texto}%"
            consulta = consulta.where(or_(Producto.nombre.ilike(patron), Producto.descripcion.ilike(patron)))
        if filtros.categoria_id is not None:
            consulta = consulta.where(Producto.categoria_id == filtros.categoria_id)
        if filtros.material_id is not None:
            consulta = consulta.where(Producto.material_id == filtros.material_id)
        if filtros.temporada_id is not None:
            consulta = consulta.where(Producto.temporada_id == filtros.temporada_id)
        if filtros.genero is not None:
            consulta = consulta.where(Producto.genero == filtros.genero)
        if filtros.precio_min is not None:
            consulta = consulta.where(Producto.precio_base >= filtros.precio_min)
        if filtros.precio_max is not None:
            consulta = consulta.where(Producto.precio_base <= filtros.precio_max)

        necesita_variante = (
            filtros.talla_id is not None or filtros.color_id is not None or filtros.solo_disponibles
        )
        if necesita_variante:
            consulta = consulta.join(ProductoVariante, ProductoVariante.producto_id == Producto.id)
            if filtros.talla_id is not None:
                consulta = consulta.where(ProductoVariante.talla_id == filtros.talla_id)
            if filtros.color_id is not None:
                consulta = consulta.where(ProductoVariante.color_id == filtros.color_id)
            if filtros.solo_disponibles:
                # Proxy hasta que exista `inventario`: "disponible" acá solo
                # significa que tiene alguna variante activa, no que haya
                # stock real. TODO(P3.1): reemplazar por disponibilidad real.
                consulta = consulta.where(ProductoVariante.activo.is_(True))
            consulta = consulta.distinct()

        consulta = consulta.order_by(Producto.id).offset(paginacion.offset).limit(paginacion.tamanio)
        return list(db.scalars(consulta).all())

    def listar_por_ids_publico(self, db: Session, producto_ids: list[int]) -> list[Producto]:
        """Para GET /catalogo/variantes/detalle: resuelve foto de producto
        para un lote de producto_id (lo usa 'stock bajo' del dashboard,
        que ya conoce el producto_id vía inventario/alertas)."""
        consulta = (
            select(Producto).where(Producto.id.in_(set(producto_ids))).options(selectinload(Producto.imagenes))
        )
        return list(db.scalars(consulta).all())

    def obtener_publico_detalle(self, db: Session, producto_id: int) -> Producto:
        producto = db.scalar(
            select(Producto)
            .where(Producto.id == producto_id, Producto.activo.is_(True))
            .options(selectinload(Producto.variantes), selectinload(Producto.imagenes))
        )
        if producto is None:
            raise NoEncontradoError("Producto no encontrado")
        return producto


class VarianteRepository(CRUDBase[ProductoVariante, VarianteActualizar, VarianteActualizar]):
    def __init__(self) -> None:
        super().__init__(ProductoVariante)

    def listar_por_producto(self, db: Session, producto_id: int) -> list[ProductoVariante]:
        return list(
            db.scalars(
                select(ProductoVariante).where(
                    ProductoVariante.producto_id == producto_id, ProductoVariante.activo.is_(True)
                )
            )
        )

    def obtener_por_combinacion(
        self, db: Session, producto_id: int, talla_id: int, color_id: int
    ) -> ProductoVariante | None:
        return db.scalar(
            select(ProductoVariante).where(
                ProductoVariante.producto_id == producto_id,
                ProductoVariante.talla_id == talla_id,
                ProductoVariante.color_id == color_id,
            )
        )

    def obtener_por_sku(self, db: Session, sku: str) -> ProductoVariante | None:
        return db.scalar(select(ProductoVariante).where(ProductoVariante.sku == sku))

    def listar_para_detalle_publico(
        self, db: Session, variante_ids: list[int]
    ) -> list[tuple[ProductoVariante, Producto, Talla, Color]]:
        """Para GET /catalogo/variantes/detalle: resuelve producto+imagen
        (+talla/color, para el carrito de la app) para un lote de
        variantes, lo usa 'se vendió hoy' del dashboard (una Venta solo
        trae variante_id, no nombre ni foto) y el carrito de compra de
        Flutter (mismo problema: CarritoDetalleRespuesta solo trae
        variante_id)."""
        consulta = (
            select(ProductoVariante, Producto, Talla, Color)
            .join(Producto, Producto.id == ProductoVariante.producto_id)
            .join(Talla, Talla.id == ProductoVariante.talla_id)
            .join(Color, Color.id == ProductoVariante.color_id)
            .where(ProductoVariante.id.in_(set(variante_ids)))
            .options(selectinload(Producto.imagenes))
        )
        return [tuple(fila) for fila in db.execute(consulta).all()]

    def obtener_por_codigo_barras(self, db: Session, codigo_barras: str) -> ProductoVariante | None:
        return db.scalar(select(ProductoVariante).where(ProductoVariante.codigo_barras == codigo_barras))

    def buscar_para_venta(
        self, db: Session, texto: str, limite: int = 20
    ) -> list[tuple[ProductoVariante, Producto, Talla, Color]]:
        """Para la caja (POS): resuelve una variante por código de barras
        exacto (lector físico) o texto libre sobre sku/nombre/código de
        producto. `productos_router` es de administración (requiere
        catalogo.gestionar, ver su docstring); esto lo usa el cajero, que
        solo tiene catalogo.ver."""
        patron = f"%{texto}%"
        consulta = (
            select(ProductoVariante, Producto, Talla, Color)
            .join(Producto, Producto.id == ProductoVariante.producto_id)
            .join(Talla, Talla.id == ProductoVariante.talla_id)
            .join(Color, Color.id == ProductoVariante.color_id)
            .where(ProductoVariante.activo.is_(True), Producto.activo.is_(True))
            .where(
                or_(
                    ProductoVariante.codigo_barras == texto,
                    ProductoVariante.sku.ilike(patron),
                    Producto.nombre.ilike(patron),
                    Producto.codigo.ilike(patron),
                )
            )
            .order_by(Producto.nombre)
            .limit(limite)
        )
        return [tuple(fila) for fila in db.execute(consulta).all()]


class TablaMedidaRepository:
    """No hereda de CRUDBase: tabla_medida no tiene columna `activo`, las
    filas se eliminan físicamente (igual que horario_sucursal)."""

    def listar_por_producto(self, db: Session, producto_id: int) -> list[TablaMedida]:
        return list(db.scalars(select(TablaMedida).where(TablaMedida.producto_id == producto_id)))

    def listar_por_categoria(self, db: Session, categoria_id: int) -> list[TablaMedida]:
        return list(db.scalars(select(TablaMedida).where(TablaMedida.categoria_id == categoria_id)))

    def obtener(self, db: Session, producto_id: int, medida_id: int) -> TablaMedida:
        medida = db.scalar(
            select(TablaMedida).where(TablaMedida.id == medida_id, TablaMedida.producto_id == producto_id)
        )
        if medida is None:
            raise NoEncontradoError("Medida no encontrada")
        return medida

    def crear(self, db: Session, producto_id: int, datos: TablaMedidaCrear) -> TablaMedida:
        medida = TablaMedida(producto_id=producto_id, **datos.model_dump())
        db.add(medida)
        db.commit()
        db.refresh(medida)
        return medida

    def actualizar(
        self, db: Session, producto_id: int, medida_id: int, datos: TablaMedidaActualizar
    ) -> TablaMedida:
        medida = self.obtener(db, producto_id, medida_id)
        for campo, valor in datos.model_dump(exclude_unset=True).items():
            setattr(medida, campo, valor)
        db.commit()
        db.refresh(medida)
        return medida

    def eliminar(self, db: Session, producto_id: int, medida_id: int) -> None:
        medida = self.obtener(db, producto_id, medida_id)
        db.delete(medida)
        db.commit()


class ImagenRepository:
    """No hereda de CRUDBase: producto_imagen no tiene columna `activo`,
    las filas se eliminan físicamente (después de borrar el archivo real
    en Cloudinary, ver service.eliminar_imagen)."""

    def listar_por_producto(self, db: Session, producto_id: int) -> list[ProductoImagen]:
        return list(
            db.scalars(
                select(ProductoImagen)
                .where(ProductoImagen.producto_id == producto_id)
                .order_by(ProductoImagen.orden)
            )
        )

    def obtener(self, db: Session, imagen_id: int) -> ProductoImagen:
        imagen = db.get(ProductoImagen, imagen_id)
        if imagen is None:
            raise NoEncontradoError("Imagen no encontrada")
        return imagen

    def crear(
        self, db: Session, producto_id: int, public_id: str, color_id: int | None, orden: int
    ) -> ProductoImagen:
        imagen = ProductoImagen(producto_id=producto_id, color_id=color_id, url=public_id, orden=orden)
        db.add(imagen)
        db.commit()
        db.refresh(imagen)
        return imagen

    def eliminar(self, db: Session, imagen_id: int) -> None:
        imagen = self.obtener(db, imagen_id)
        db.delete(imagen)
        db.commit()

    def marcar_principal(self, db: Session, imagen: ProductoImagen) -> ProductoImagen:
        db.query(ProductoImagen).filter(
            ProductoImagen.producto_id == imagen.producto_id, ProductoImagen.id != imagen.id
        ).update({"es_principal": False})
        imagen.es_principal = True
        db.commit()
        db.refresh(imagen)
        return imagen


class FavoritoRepository:
    """Composite PK (cliente_id, variante_id), sin columna `activo`."""

    def listar_por_cliente(self, db: Session, cliente_id: int) -> list[Favorito]:
        return list(
            db.scalars(
                select(Favorito)
                .where(Favorito.cliente_id == cliente_id)
                .options(selectinload(Favorito.variante).selectinload(ProductoVariante.producto))
                .order_by(Favorito.creado_en.desc())
            )
        )

    def obtener(self, db: Session, cliente_id: int, variante_id: int) -> Favorito | None:
        return db.get(Favorito, (cliente_id, variante_id))

    def agregar(self, db: Session, cliente_id: int, variante_id: int) -> Favorito:
        existente = self.obtener(db, cliente_id, variante_id)
        if existente is not None:
            return existente  # agregar un favorito ya agregado es idempotente
        favorito = Favorito(cliente_id=cliente_id, variante_id=variante_id)
        db.add(favorito)
        db.commit()
        db.refresh(favorito)
        return favorito

    def quitar(self, db: Session, cliente_id: int, variante_id: int) -> None:
        favorito = self.obtener(db, cliente_id, variante_id)
        if favorito is None:
            raise NoEncontradoError("Favorito no encontrado")
        db.delete(favorito)
        db.commit()
