import re
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import storage
from app.core.deps import ParametrosPaginacion
from app.core.exceptions import ConflictoError, DomainError, NoEncontradoError
from app.catalogo.models import (
    Categoria,
    Coleccion,
    Color,
    Material,
    Producto,
    ProductoImagen,
    ProductoVariante,
    Talla,
    TablaMedida,
    Temporada,
)
from app.catalogo.repository import (
    CategoriaRepository,
    ColeccionRepository,
    ColorRepository,
    FavoritoRepository,
    ImagenRepository,
    MaterialRepository,
    ProductoRepository,
    TablaMedidaRepository,
    TallaRepository,
    TemporadaRepository,
    VarianteRepository,
)
from app.catalogo.schemas import (
    CategoriaActualizar,
    CategoriaCrear,
    CatalogoDetalleRespuesta,
    CatalogoItemRespuesta,
    ColeccionActualizar,
    ColeccionCrear,
    ColorActualizar,
    ColorCrear,
    FavoritoRespuesta,
    FiltrosCatalogo,
    Genero,
    ImagenRespuesta,
    MaterialActualizar,
    MaterialCrear,
    ProductoActualizar,
    ProductoCrear,
    ProductoImagenLookupItem,
    TablaMedidaActualizar,
    TablaMedidaCrear,
    TallaActualizar,
    TallaCrear,
    TemporadaActualizar,
    TemporadaCrear,
    ValoresReferenciaCatalogo,
    VarianteActualizar,
    VarianteCatalogoRespuesta,
    VariantesGenerarRequest,
)
from app.seguridad import service as seguridad_service

categoria_repo = CategoriaRepository()
temporada_repo = TemporadaRepository()
coleccion_repo = ColeccionRepository()
talla_repo = TallaRepository()
color_repo = ColorRepository()
material_repo = MaterialRepository()
producto_repo = ProductoRepository()
variante_repo = VarianteRepository()
medida_repo = TablaMedidaRepository()
imagen_repo = ImagenRepository()
favorito_repo = FavoritoRepository()

CONTENT_TYPES_PERMITIDOS = {"image/jpeg", "image/png", "image/webp"}
TAMANIO_MAXIMO_BYTES = 10 * 1024 * 1024  # 10MB

# CLAUDE.md: "Alcance del probador virtual: solo prendas superiores
# masculinas (poleras, camisas, chamarras)". No hay columna en `categoria`
# para marcar esto, así que se resuelve por nombre. Si el admin manda
# admite_probador=True en una categoría que no matchea acá, se ignora.
PALABRAS_TORSO_SUPERIOR = {"polera", "camisa", "chamarra"}


def _crearia_ciclo(db: Session, categoria_id: int, nuevo_padre_id: int) -> bool:
    """True si engancharle `nuevo_padre_id` como padre de `categoria_id`
    crea un ciclo (incluye el caso trivial de ser su propio padre)."""
    actual: int | None = nuevo_padre_id
    visitados: set[int] = set()
    while actual is not None:
        if actual == categoria_id:
            return True
        if actual in visitados:
            break
        visitados.add(actual)
        padre = db.get(Categoria, actual)
        actual = padre.categoria_padre_id if padre else None
    return False


def _validar_padre(db: Session, categoria_id: int | None, categoria_padre_id: int | None) -> None:
    if categoria_padre_id is None:
        return
    padre = db.get(Categoria, categoria_padre_id)
    if padre is None or not padre.activo:
        raise NoEncontradoError("Categoría padre no encontrada")
    if categoria_id is not None and _crearia_ciclo(db, categoria_id, categoria_padre_id):
        raise DomainError("Una categoría no puede ser su propio padre ni crear un ciclo")


def listar_categorias(db: Session, paginacion: ParametrosPaginacion) -> list[Categoria]:
    return list(categoria_repo.listar(db, paginacion))


def obtener_categoria(db: Session, categoria_id: int) -> Categoria:
    return categoria_repo.obtener(db, categoria_id)


def crear_categoria(db: Session, datos: CategoriaCrear) -> Categoria:
    _validar_padre(db, None, datos.categoria_padre_id)
    return categoria_repo.crear(db, datos)


def actualizar_categoria(db: Session, categoria_id: int, datos: CategoriaActualizar) -> Categoria:
    if datos.categoria_padre_id is not None:
        _validar_padre(db, categoria_id, datos.categoria_padre_id)
    return categoria_repo.actualizar(db, categoria_id, datos)


def desactivar_categoria(db: Session, categoria_id: int) -> Categoria:
    if categoria_repo.listar_hijos(db, categoria_id):
        raise ConflictoError("No se puede desactivar: la categoría tiene subcategorías activas")
    tiene_productos = db.scalar(
        select(Producto).where(Producto.categoria_id == categoria_id, Producto.activo.is_(True))
    )
    if tiene_productos is not None:
        raise ConflictoError("No se puede desactivar: la categoría tiene productos activos")
    return categoria_repo.desactivar(db, categoria_id)


# ---- Tallas / colores / materiales -------------------------------------------
# Sin columna `activo` (CRUDBaseSinActivo): se eliminan físicamente, igual
# que horario_sucursal/producto_imagen.


def listar_tallas(db: Session, paginacion: ParametrosPaginacion) -> list[Talla]:
    return list(talla_repo.listar(db, paginacion))


def crear_talla(db: Session, datos: TallaCrear) -> Talla:
    return talla_repo.crear(db, datos)


def actualizar_talla(db: Session, talla_id: int, datos: TallaActualizar) -> Talla:
    return talla_repo.actualizar(db, talla_id, datos)


def eliminar_talla(db: Session, talla_id: int) -> None:
    talla_repo.eliminar(db, talla_id)


def listar_colores(db: Session, paginacion: ParametrosPaginacion) -> list[Color]:
    return list(color_repo.listar(db, paginacion))


def obtener_color(db: Session, color_id: int) -> Color:
    return color_repo.obtener(db, color_id)


def crear_color(db: Session, datos: ColorCrear) -> Color:
    return color_repo.crear(db, datos)


def actualizar_color(db: Session, color_id: int, datos: ColorActualizar) -> Color:
    return color_repo.actualizar(db, color_id, datos)


def eliminar_color(db: Session, color_id: int) -> None:
    color_repo.eliminar(db, color_id)


def listar_materiales(db: Session, paginacion: ParametrosPaginacion) -> list[Material]:
    return list(material_repo.listar(db, paginacion))


def obtener_material(db: Session, material_id: int) -> Material:
    return material_repo.obtener(db, material_id)


def crear_material(db: Session, datos: MaterialCrear) -> Material:
    return material_repo.crear(db, datos)


def actualizar_material(db: Session, material_id: int, datos: MaterialActualizar) -> Material:
    return material_repo.actualizar(db, material_id, datos)


def eliminar_material(db: Session, material_id: int) -> None:
    material_repo.eliminar(db, material_id)


# ---- Temporadas y colecciones -------------------------------------------------


def listar_temporadas(db: Session, paginacion: ParametrosPaginacion) -> list[Temporada]:
    return list(temporada_repo.listar(db, paginacion))


def obtener_temporada(db: Session, temporada_id: int) -> Temporada:
    return temporada_repo.obtener(db, temporada_id)


def crear_temporada(db: Session, datos: TemporadaCrear) -> Temporada:
    return temporada_repo.crear(db, datos)


def desactivar_temporada(db: Session, temporada_id: int) -> Temporada:
    return temporada_repo.desactivar(db, temporada_id)


def actualizar_temporada(db: Session, temporada_id: int, datos: TemporadaActualizar) -> Temporada:
    temporada = temporada_repo.obtener(db, temporada_id)
    inicio = datos.fecha_inicio if "fecha_inicio" in datos.model_fields_set else temporada.fecha_inicio
    fin = datos.fecha_fin if "fecha_fin" in datos.model_fields_set else temporada.fecha_fin
    if inicio and fin and fin <= inicio:
        raise DomainError("fecha_fin debe ser posterior a fecha_inicio")
    return temporada_repo.actualizar(db, temporada_id, datos)


def listar_colecciones(db: Session, paginacion: ParametrosPaginacion) -> list[Coleccion]:
    return list(coleccion_repo.listar(db, paginacion))


def obtener_coleccion(db: Session, coleccion_id: int) -> Coleccion:
    return coleccion_repo.obtener(db, coleccion_id)


def crear_coleccion(db: Session, datos: ColeccionCrear) -> Coleccion:
    if datos.temporada_id is not None:
        temporada_repo.obtener(db, datos.temporada_id)
    return coleccion_repo.crear(db, datos)


def actualizar_coleccion(db: Session, coleccion_id: int, datos: ColeccionActualizar) -> Coleccion:
    if datos.temporada_id is not None:
        temporada_repo.obtener(db, datos.temporada_id)
    return coleccion_repo.actualizar(db, coleccion_id, datos)


def desactivar_coleccion(db: Session, coleccion_id: int) -> Coleccion:
    return coleccion_repo.desactivar(db, coleccion_id)


# ---- Producto y variantes ---------------------------------------------------


def _es_torso_superior(db: Session, categoria: Categoria) -> bool:
    actual: Categoria | None = categoria
    visitados: set[int] = set()
    while actual is not None and actual.id not in visitados:
        visitados.add(actual.id)
        nombre = actual.nombre.strip().lower()
        if any(palabra in nombre for palabra in PALABRAS_TORSO_SUPERIOR):
            return True
        actual = db.get(Categoria, actual.categoria_padre_id) if actual.categoria_padre_id else None
    return False


def _resolver_admite_probador(db: Session, categoria_id: int, admite_probador_pedido: bool) -> bool:
    if not admite_probador_pedido:
        return False
    categoria = categoria_repo.obtener(db, categoria_id)
    return _es_torso_superior(db, categoria)


def _validar_referencias_producto(
    db: Session,
    categoria_id: int | None,
    material_id: int | None,
    temporada_id: int | None,
    coleccion_id: int | None,
) -> None:
    if categoria_id is not None:
        categoria_repo.obtener(db, categoria_id)
    if material_id is not None:
        material_repo.obtener(db, material_id)
    if temporada_id is not None:
        temporada_repo.obtener(db, temporada_id)
    if coleccion_id is not None:
        coleccion_repo.obtener(db, coleccion_id)


def listar_productos(db: Session, paginacion: ParametrosPaginacion) -> list[Producto]:
    return list(producto_repo.listar(db, paginacion))


def desactivar_producto(db: Session, producto_id: int) -> Producto:
    return producto_repo.desactivar(db, producto_id)


def crear_producto(db: Session, datos: ProductoCrear, creado_por: int | None) -> Producto:
    _validar_referencias_producto(db, datos.categoria_id, datos.material_id, datos.temporada_id, datos.coleccion_id)

    admite_probador_real = _resolver_admite_probador(db, datos.categoria_id, datos.admite_probador)
    datos = datos.model_copy(update={"admite_probador": admite_probador_real})

    producto = producto_repo.crear(db, datos, creado_por)
    generar_variantes(db, producto, datos.tallas_ids, datos.colores_ids)
    return producto


def actualizar_producto(db: Session, producto_id: int, datos: ProductoActualizar) -> Producto:
    producto = producto_repo.obtener(db, producto_id)
    _validar_referencias_producto(
        db, datos.categoria_id, datos.material_id, datos.temporada_id, datos.coleccion_id
    )

    cambia_categoria = "categoria_id" in datos.model_fields_set
    cambia_probador = "admite_probador" in datos.model_fields_set
    if cambia_categoria or cambia_probador:
        categoria_id = datos.categoria_id if cambia_categoria else producto.categoria_id
        admite_probador_pedido = datos.admite_probador if cambia_probador else producto.admite_probador
        datos = datos.model_copy(
            update={"admite_probador": _resolver_admite_probador(db, categoria_id, admite_probador_pedido)}
        )

    return producto_repo.actualizar(db, producto_id, datos)


def _slug_color(nombre: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", nombre).upper()


def _sku_unico(db: Session, sku_base: str) -> str:
    sku = sku_base
    sufijo = 2
    while variante_repo.obtener_por_sku(db, sku) is not None:
        sku = f"{sku_base}-{sufijo}"
        sufijo += 1
    return sku


def _obtener_tallas(db: Session, tallas_ids: list[int]) -> list[Talla]:
    ids_unicos = set(tallas_ids)
    tallas = list(db.scalars(select(Talla).where(Talla.id.in_(ids_unicos))))
    if len(tallas) != len(ids_unicos):
        raise NoEncontradoError("Una o más tallas no existen")
    return tallas


def _obtener_colores(db: Session, colores_ids: list[int]) -> list[Color]:
    ids_unicos = set(colores_ids)
    colores = list(db.scalars(select(Color).where(Color.id.in_(ids_unicos))))
    if len(colores) != len(ids_unicos):
        raise NoEncontradoError("Uno o más colores no existen")
    return colores


def generar_variantes(
    db: Session, producto: Producto, tallas_ids: list[int], colores_ids: list[int]
) -> list[ProductoVariante]:
    """Combinatoria talla × color con SKU {codigo_producto}-{codigo_talla}-{codigo_color}.

    Si una combinación ya existe y está activa, se salta: llamar esto de
    nuevo agregando un color no duplica las variantes que ya estaban. Si
    existe pero fue desactivada, se reactiva (mismo sku) en vez de
    quedar huérfana para siempre."""
    tallas = _obtener_tallas(db, tallas_ids)
    colores = _obtener_colores(db, colores_ids)

    creadas: list[ProductoVariante] = []
    for talla in tallas:
        for color in colores:
            existente = variante_repo.obtener_por_combinacion(db, producto.id, talla.id, color.id)
            if existente is not None:
                if not existente.activo:
                    existente.activo = True
                    creadas.append(existente)
                continue
            sku_base = f"{producto.codigo}-{talla.codigo}-{_slug_color(color.nombre)}".upper()
            sku = _sku_unico(db, sku_base)
            variante = ProductoVariante(producto_id=producto.id, talla_id=talla.id, color_id=color.id, sku=sku)
            db.add(variante)
            creadas.append(variante)

    db.commit()
    for variante in creadas:
        db.refresh(variante)
    return creadas


def agregar_variantes(db: Session, producto_id: int, datos: VariantesGenerarRequest) -> list[ProductoVariante]:
    producto = producto_repo.obtener(db, producto_id)
    return generar_variantes(db, producto, datos.tallas_ids, datos.colores_ids)


def listar_variantes_producto(db: Session, producto_id: int) -> list[ProductoVariante]:
    producto_repo.obtener(db, producto_id)  # 404 si no existe
    return variante_repo.listar_por_producto(db, producto_id)


def buscar_variantes_para_venta(
    db: Session, texto: str
) -> list[tuple[ProductoVariante, Producto, Talla, Color]]:
    return variante_repo.buscar_para_venta(db, texto)


def actualizar_variante(db: Session, variante_id: int, datos: VarianteActualizar) -> ProductoVariante:
    if datos.codigo_barras is not None:
        existente = variante_repo.obtener_por_codigo_barras(db, datos.codigo_barras)
        if existente is not None and existente.id != variante_id:
            raise ConflictoError("Ya existe una variante con ese código de barras")
    if datos.activo is False:
        # TODO(P3.1): bloquear si stock.cantidad_fisica > 0 una vez que
        # exista el paquete `inventario`. Cuando exista, esto llama a
        # inventario.service, nunca consulta la tabla stock directamente.
        pass
    return variante_repo.actualizar(db, variante_id, datos)


def desactivar_variante(db: Session, variante_id: int) -> ProductoVariante:
    # Mismo TODO que actualizar_variante: bloquear si hay stock físico
    # cuando exista `inventario` (P3.1).
    return variante_repo.desactivar(db, variante_id)


# ---- Tabla de medidas ---------------------------------------------------------


def listar_medidas_producto(db: Session, producto_id: int) -> list[TablaMedida]:
    producto_repo.obtener(db, producto_id)  # 404 si no existe
    return list(medida_repo.listar_por_producto(db, producto_id))


def crear_medida(db: Session, producto_id: int, datos: TablaMedidaCrear) -> TablaMedida:
    producto_repo.obtener(db, producto_id)
    talla_repo.obtener(db, datos.talla_id)
    return medida_repo.crear(db, producto_id, datos)


def actualizar_medida(db: Session, producto_id: int, medida_id: int, datos: TablaMedidaActualizar) -> TablaMedida:
    if datos.talla_id is not None:
        talla_repo.obtener(db, datos.talla_id)
    return medida_repo.actualizar(db, producto_id, medida_id, datos)


def eliminar_medida(db: Session, producto_id: int, medida_id: int) -> None:
    medida_repo.eliminar(db, producto_id, medida_id)


# ---- Imágenes de producto ------------------------------------------------------


def subir_imagen_producto(
    db: Session,
    producto_id: int,
    contenido: bytes,
    content_type: str | None,
    color_id: int | None,
    es_principal: bool,
) -> tuple[ProductoImagen, str]:
    producto_repo.obtener(db, producto_id)
    if color_id is not None:
        color_repo.obtener(db, color_id)

    if content_type not in CONTENT_TYPES_PERMITIDOS:
        raise DomainError("El archivo debe ser una imagen (jpeg, png o webp)")
    if len(contenido) > TAMANIO_MAXIMO_BYTES:
        raise DomainError("La imagen supera el tamaño máximo permitido (10MB)")

    public_id = storage.subir_imagen(contenido, storage.carpeta_producto(producto_id))

    orden = len(imagen_repo.listar_por_producto(db, producto_id))
    imagen = imagen_repo.crear(db, producto_id, public_id, color_id, orden)

    if es_principal:
        imagen = imagen_repo.marcar_principal(db, imagen)

    return imagen, storage.url_catalogo(public_id)


def eliminar_imagen(db: Session, imagen_id: int) -> None:
    imagen = imagen_repo.obtener(db, imagen_id)
    # Primero se borra el archivo real; si eso falla, la fila de la base
    # se conserva (mejor una referencia a un archivo que sigue vivo que
    # perder la referencia a uno que capaz no se borró).
    storage.eliminar_imagen(imagen.url)
    imagen_repo.eliminar(db, imagen_id)


def marcar_imagen_principal(db: Session, imagen_id: int) -> tuple[ProductoImagen, str]:
    imagen = imagen_repo.obtener(db, imagen_id)
    imagen = imagen_repo.marcar_principal(db, imagen)
    return imagen, storage.url_catalogo(imagen.url)


# ---- Catálogo público ------------------------------------------------------


def _imagen_principal_url(producto: Producto) -> str | None:
    if not producto.imagenes:
        return None
    principal = next((img for img in producto.imagenes if img.es_principal), producto.imagenes[0])
    return storage.url_catalogo(principal.url)


def _a_item_catalogo(producto: Producto) -> CatalogoItemRespuesta:
    return CatalogoItemRespuesta(
        id=producto.id,
        codigo=producto.codigo,
        nombre=producto.nombre,
        categoria_id=producto.categoria_id,
        genero=producto.genero,
        precio_base=producto.precio_base,
        admite_probador=producto.admite_probador,
        imagen_principal=_imagen_principal_url(producto),
    )


def listar_catalogo(db: Session, paginacion: ParametrosPaginacion) -> list[CatalogoItemRespuesta]:
    productos = producto_repo.listar_publico(db, paginacion)
    return [_a_item_catalogo(p) for p in productos]


def buscar_catalogo(
    db: Session, paginacion: ParametrosPaginacion, filtros: FiltrosCatalogo
) -> list[CatalogoItemRespuesta]:
    productos = producto_repo.buscar_publico(db, paginacion, filtros)
    return [_a_item_catalogo(p) for p in productos]


def resolver_imagen_lookup(
    db: Session, variante_ids: list[int] | None, producto_ids: list[int] | None
) -> list[ProductoImagenLookupItem]:
    """Resuelve nombre+foto en lote para el dashboard del back office (ver
    ProductoImagenLookupItem). No filtra por `activo`: quien llama ya
    conoce estos ids por una venta o una alerta de stock real, así que
    interesa mostrar la prenda aunque haya quedado inactiva después."""
    resultados: list[ProductoImagenLookupItem] = []
    if variante_ids:
        for variante, producto, talla, color in variante_repo.listar_para_detalle_publico(db, variante_ids):
            resultados.append(
                ProductoImagenLookupItem(
                    variante_id=variante.id,
                    producto_id=producto.id,
                    producto_nombre=producto.nombre,
                    imagen_principal=_imagen_principal_url(producto),
                    talla_codigo=talla.codigo,
                    color_nombre=color.nombre,
                )
            )
    if producto_ids:
        for producto in producto_repo.listar_por_ids_publico(db, producto_ids):
            resultados.append(
                ProductoImagenLookupItem(
                    producto_id=producto.id,
                    producto_nombre=producto.nombre,
                    imagen_principal=_imagen_principal_url(producto),
                )
            )
    return resultados


def _disponibilidad_variante(variante_id: int, sucursal_id: int | None) -> int | None:
    """TODO(P3.1): pedir la disponibilidad real a inventario.service una
    vez que exista ese paquete (nunca consultar la tabla `stock` acá
    directamente — regla de aislamiento entre paquetes). Por ahora no hay
    ninguna noción de stock, así que siempre devuelve None."""
    return None


def obtener_detalle_catalogo(
    db: Session, producto_id: int, sucursal_id: int | None = None
) -> CatalogoDetalleRespuesta:
    producto = producto_repo.obtener_publico_detalle(db, producto_id)

    variantes = [
        VarianteCatalogoRespuesta(
            id=v.id,
            talla_id=v.talla_id,
            color_id=v.color_id,
            sku=v.sku,
            precio_efectivo=v.precio if v.precio is not None else producto.precio_base,
            cantidad_disponible=_disponibilidad_variante(v.id, sucursal_id),
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


# ---- Favoritos --------------------------------------------------------------


def listar_favoritos(db: Session, usuario_id: int) -> list[FavoritoRespuesta]:
    cliente = seguridad_service.obtener_perfil_cliente(db, usuario_id)
    favoritos = favorito_repo.listar_por_cliente(db, cliente.id)
    return [FavoritoRespuesta.from_modelo(f) for f in favoritos]


def agregar_favorito(db: Session, usuario_id: int, variante_id: int) -> FavoritoRespuesta:
    cliente = seguridad_service.obtener_perfil_cliente(db, usuario_id)
    variante_repo.obtener(db, variante_id)  # 404 si no existe o está inactiva
    favorito = favorito_repo.agregar(db, cliente.id, variante_id)
    return FavoritoRespuesta.from_modelo(favorito)


def quitar_favorito(db: Session, usuario_id: int, variante_id: int) -> None:
    cliente = seguridad_service.obtener_perfil_cliente(db, usuario_id)
    favorito_repo.quitar(db, cliente.id, variante_id)


# ---- Punto de entrada para otros paquetes ------------------------------------


def obtener_variante(db: Session, variante_id: int) -> ProductoVariante:
    """Para que otros paquetes (p. ej. `probador`, `inventario`) validen una
    variante sin consultar producto_variante directamente."""
    return variante_repo.obtener(db, variante_id)


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
    """Para que `inteligencia` (P6.1, búsqueda por voz) arme el prompt de
    Groq con los valores válidos reales, sin consultar categoria/material/
    color/talla/temporada directamente."""
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
    """Para `inteligencia.service`: matchea cada nombre que devolvió Groq
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
    """Para `inteligencia` (P6.3, reporte por voz): matchea el nombre de
    categoría que devolvió Groq sin consultar `categoria` directamente.
    Sin match, devuelve None -- no rompe el reporte."""
    return _resolver_por_nombre(db, Categoria.id, Categoria.nombre, nombre)


def listar_variantes_temporada_vigente(db: Session) -> set[int]:
    """Para `inteligencia` (P6.2, capa de reglas): variantes activas cuyo
    producto pertenece a una temporada vigente (`Temporada.activo`, mismo
    criterio que `listar_valores_referencia`). Un producto sin temporada
    asignada no cuenta como vigente."""
    filas = db.scalars(
        select(ProductoVariante.id)
        .join(Producto, Producto.id == ProductoVariante.producto_id)
        .join(Temporada, Temporada.id == Producto.temporada_id)
        .where(ProductoVariante.activo.is_(True), Producto.activo.is_(True), Temporada.activo.is_(True))
    )
    return set(filas)


def listar_variantes_de_producto(db: Session, producto_id: int) -> set[int]:
    """Para `inteligencia` (P6.2): variantes de un producto, para excluirlo
    de su propio carrusel de recomendaciones (detalle de prenda)."""
    return set(db.scalars(select(ProductoVariante.id).where(ProductoVariante.producto_id == producto_id)))


def listar_items_por_variantes(db: Session, variante_ids: list[int]) -> dict[int, CatalogoItemRespuesta]:
    """Para `inteligencia` (P6.2): resuelve cada variante candidata a la
    tarjeta de su producto (imagen, nombre, precio), sin consultar
    producto_variante/producto directamente. Variantes de un mismo
    producto resuelven al mismo `CatalogoItemRespuesta` (mismo `id`) --
    el llamador decide si colapsarlas."""
    if not variante_ids:
        return {}
    filas = db.execute(
        select(ProductoVariante.id, Producto)
        .join(Producto, Producto.id == ProductoVariante.producto_id)
        .where(ProductoVariante.id.in_(variante_ids))
    ).all()
    return {variante_id: _a_item_catalogo(producto) for variante_id, producto in filas}
