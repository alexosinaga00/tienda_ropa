from decimal import Decimal

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import ParametrosPaginacion, parametros_paginacion
from app.core.rate_limit import limiter
from app.core.security import get_current_user, require_permission
from app.catalogo.casos_uso.cu07_gestionar_catalogo_maestro import (
    GestionarCategorias,
    GestionarColecciones,
    GestionarColores,
    GestionarMateriales,
    GestionarTallas,
    GestionarTemporadas,
)
from app.catalogo.casos_uso.cu08_gestionar_productos import GestionarProductos
from app.catalogo.casos_uso.cu09_consultar_catalogo import ConsultarCatalogo
from app.catalogo.casos_uso.cu10_buscar_filtrar_prendas import BuscarFiltrarPrendas
from app.catalogo.casos_uso.cu36_gestionar_favoritos import GestionarFavoritos
from app.catalogo.schemas import (
    CategoriaActualizar,
    CategoriaCrear,
    CategoriaRespuesta,
    CatalogoDetalleRespuesta,
    CatalogoItemRespuesta,
    ColeccionActualizar,
    ColeccionCrear,
    ColeccionRespuesta,
    ColorActualizar,
    ColorCrear,
    ColorRespuesta,
    FavoritoCrear,
    FavoritoRespuesta,
    FiltrosCatalogo,
    Genero,
    ImagenRespuesta,
    MaterialActualizar,
    MaterialCrear,
    MaterialRespuesta,
    ProductoActualizar,
    ProductoCrear,
    ProductoImagenLookupItem,
    ProductoRespuesta,
    TablaMedidaActualizar,
    TablaMedidaCrear,
    TablaMedidaRespuesta,
    TallaActualizar,
    TallaCrear,
    TallaRespuesta,
    TemporadaActualizar,
    TemporadaCrear,
    TemporadaRespuesta,
    VarianteActualizar,
    VarianteBusquedaRespuesta,
    VarianteRespuesta,
    VariantesGenerarRequest,
)

def paginacion_catalogo(
    pagina: int = Query(default=1, ge=1), tamanio: int = Query(default=20, ge=1, le=50)
) -> ParametrosPaginacion:
    return ParametrosPaginacion(pagina=pagina, tamanio=tamanio)

PERMISO_CATALOGO = "catalogo.gestionar"
admin_requerido = Depends(require_permission(PERMISO_CATALOGO))

cu_categorias = GestionarCategorias()
cu_tallas = GestionarTallas()
cu_colores = GestionarColores()
cu_materiales = GestionarMateriales()
cu_temporadas = GestionarTemporadas()
cu_colecciones = GestionarColecciones()
cu_productos = GestionarProductos()
cu_consultar_catalogo = ConsultarCatalogo()
cu_buscar_prendas = BuscarFiltrarPrendas()
cu_favoritos = GestionarFavoritos()

# ---- /api/v1/categorias ---------------------------------------------------

categorias_router = APIRouter(prefix="/api/v1/categorias", tags=["categorias"])


@categorias_router.get("", response_model=list[CategoriaRespuesta])
def listar_categorias(
    db: Session = Depends(get_db), paginacion: ParametrosPaginacion = Depends(parametros_paginacion)
) -> list[CategoriaRespuesta]:
    return cu_categorias.listar(db, paginacion)


@categorias_router.get("/{categoria_id}", response_model=CategoriaRespuesta)
def obtener_categoria(categoria_id: int, db: Session = Depends(get_db)) -> CategoriaRespuesta:
    return cu_categorias.obtener(db, categoria_id)


@categorias_router.post(
    "", response_model=CategoriaRespuesta, status_code=status.HTTP_201_CREATED, dependencies=[admin_requerido]
)
def crear_categoria(datos: CategoriaCrear, db: Session = Depends(get_db)) -> CategoriaRespuesta:
    return cu_categorias.crear(db, datos)


@categorias_router.put(
    "/{categoria_id}", response_model=CategoriaRespuesta, dependencies=[admin_requerido]
)
def actualizar_categoria(
    categoria_id: int, datos: CategoriaActualizar, db: Session = Depends(get_db)
) -> CategoriaRespuesta:
    return cu_categorias.actualizar(db, categoria_id, datos)


@categorias_router.delete(
    "/{categoria_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[admin_requerido]
)
def desactivar_categoria(categoria_id: int, db: Session = Depends(get_db)) -> None:
    cu_categorias.desactivar(db, categoria_id)


# ---- /api/v1/tallas -----------------------------------------------------

tallas_router = APIRouter(prefix="/api/v1/tallas", tags=["tallas"])


@tallas_router.get("", response_model=list[TallaRespuesta])
def listar_tallas(
    db: Session = Depends(get_db), paginacion: ParametrosPaginacion = Depends(parametros_paginacion)
) -> list[TallaRespuesta]:
    return cu_tallas.listar(db, paginacion)


@tallas_router.get("/{talla_id}", response_model=TallaRespuesta)
def obtener_talla(talla_id: int, db: Session = Depends(get_db)) -> TallaRespuesta:
    return cu_tallas.obtener(db, talla_id)


@tallas_router.post(
    "", response_model=TallaRespuesta, status_code=status.HTTP_201_CREATED, dependencies=[admin_requerido]
)
def crear_talla(datos: TallaCrear, db: Session = Depends(get_db)) -> TallaRespuesta:
    return cu_tallas.crear(db, datos)


@tallas_router.put("/{talla_id}", response_model=TallaRespuesta, dependencies=[admin_requerido])
def actualizar_talla(talla_id: int, datos: TallaActualizar, db: Session = Depends(get_db)) -> TallaRespuesta:
    return cu_tallas.actualizar(db, talla_id, datos)


@tallas_router.delete("/{talla_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[admin_requerido])
def eliminar_talla(talla_id: int, db: Session = Depends(get_db)) -> None:
    cu_tallas.eliminar(db, talla_id)


# ---- /api/v1/colores -------------------------------------------------------

colores_router = APIRouter(prefix="/api/v1/colores", tags=["colores"])


@colores_router.get("", response_model=list[ColorRespuesta])
def listar_colores(
    db: Session = Depends(get_db), paginacion: ParametrosPaginacion = Depends(parametros_paginacion)
) -> list[ColorRespuesta]:
    return cu_colores.listar(db, paginacion)


@colores_router.get("/{color_id}", response_model=ColorRespuesta)
def obtener_color(color_id: int, db: Session = Depends(get_db)) -> ColorRespuesta:
    return cu_colores.obtener(db, color_id)


@colores_router.post(
    "", response_model=ColorRespuesta, status_code=status.HTTP_201_CREATED, dependencies=[admin_requerido]
)
def crear_color(datos: ColorCrear, db: Session = Depends(get_db)) -> ColorRespuesta:
    return cu_colores.crear(db, datos)


@colores_router.put("/{color_id}", response_model=ColorRespuesta, dependencies=[admin_requerido])
def actualizar_color(color_id: int, datos: ColorActualizar, db: Session = Depends(get_db)) -> ColorRespuesta:
    return cu_colores.actualizar(db, color_id, datos)


@colores_router.delete("/{color_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[admin_requerido])
def eliminar_color(color_id: int, db: Session = Depends(get_db)) -> None:
    cu_colores.eliminar(db, color_id)


# ---- /api/v1/materiales ---------------------------------------------------

materiales_router = APIRouter(prefix="/api/v1/materiales", tags=["materiales"])


@materiales_router.get("", response_model=list[MaterialRespuesta])
def listar_materiales(
    db: Session = Depends(get_db), paginacion: ParametrosPaginacion = Depends(parametros_paginacion)
) -> list[MaterialRespuesta]:
    return cu_materiales.listar(db, paginacion)


@materiales_router.get("/{material_id}", response_model=MaterialRespuesta)
def obtener_material(material_id: int, db: Session = Depends(get_db)) -> MaterialRespuesta:
    return cu_materiales.obtener(db, material_id)


@materiales_router.post(
    "", response_model=MaterialRespuesta, status_code=status.HTTP_201_CREATED, dependencies=[admin_requerido]
)
def crear_material(datos: MaterialCrear, db: Session = Depends(get_db)) -> MaterialRespuesta:
    return cu_materiales.crear(db, datos)


@materiales_router.put(
    "/{material_id}", response_model=MaterialRespuesta, dependencies=[admin_requerido]
)
def actualizar_material(
    material_id: int, datos: MaterialActualizar, db: Session = Depends(get_db)
) -> MaterialRespuesta:
    return cu_materiales.actualizar(db, material_id, datos)


@materiales_router.delete(
    "/{material_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[admin_requerido]
)
def eliminar_material(material_id: int, db: Session = Depends(get_db)) -> None:
    cu_materiales.eliminar(db, material_id)


# ---- /api/v1/temporadas ---------------------------------------------------

temporadas_router = APIRouter(prefix="/api/v1/temporadas", tags=["temporadas"])


@temporadas_router.get("", response_model=list[TemporadaRespuesta])
def listar_temporadas(
    db: Session = Depends(get_db), paginacion: ParametrosPaginacion = Depends(parametros_paginacion)
) -> list[TemporadaRespuesta]:
    return cu_temporadas.listar(db, paginacion)


@temporadas_router.get("/{temporada_id}", response_model=TemporadaRespuesta)
def obtener_temporada(temporada_id: int, db: Session = Depends(get_db)) -> TemporadaRespuesta:
    return cu_temporadas.obtener(db, temporada_id)


@temporadas_router.post(
    "", response_model=TemporadaRespuesta, status_code=status.HTTP_201_CREATED, dependencies=[admin_requerido]
)
def crear_temporada(datos: TemporadaCrear, db: Session = Depends(get_db)) -> TemporadaRespuesta:
    return cu_temporadas.crear(db, datos)


@temporadas_router.put(
    "/{temporada_id}", response_model=TemporadaRespuesta, dependencies=[admin_requerido]
)
def actualizar_temporada(
    temporada_id: int, datos: TemporadaActualizar, db: Session = Depends(get_db)
) -> TemporadaRespuesta:
    return cu_temporadas.actualizar(db, temporada_id, datos)


@temporadas_router.delete(
    "/{temporada_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[admin_requerido]
)
def desactivar_temporada(temporada_id: int, db: Session = Depends(get_db)) -> None:
    cu_temporadas.desactivar(db, temporada_id)


# ---- /api/v1/colecciones ---------------------------------------------------

colecciones_router = APIRouter(prefix="/api/v1/colecciones", tags=["colecciones"])


@colecciones_router.get("", response_model=list[ColeccionRespuesta])
def listar_colecciones(
    db: Session = Depends(get_db), paginacion: ParametrosPaginacion = Depends(parametros_paginacion)
) -> list[ColeccionRespuesta]:
    return cu_colecciones.listar(db, paginacion)


@colecciones_router.get("/{coleccion_id}", response_model=ColeccionRespuesta)
def obtener_coleccion(coleccion_id: int, db: Session = Depends(get_db)) -> ColeccionRespuesta:
    return cu_colecciones.obtener(db, coleccion_id)


@colecciones_router.post(
    "", response_model=ColeccionRespuesta, status_code=status.HTTP_201_CREATED, dependencies=[admin_requerido]
)
def crear_coleccion(datos: ColeccionCrear, db: Session = Depends(get_db)) -> ColeccionRespuesta:
    return cu_colecciones.crear(db, datos)


@colecciones_router.put(
    "/{coleccion_id}", response_model=ColeccionRespuesta, dependencies=[admin_requerido]
)
def actualizar_coleccion(
    coleccion_id: int, datos: ColeccionActualizar, db: Session = Depends(get_db)
) -> ColeccionRespuesta:
    return cu_colecciones.actualizar(db, coleccion_id, datos)


@colecciones_router.delete(
    "/{coleccion_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[admin_requerido]
)
def desactivar_coleccion(coleccion_id: int, db: Session = Depends(get_db)) -> None:
    cu_colecciones.desactivar(db, coleccion_id)


# ---- /api/v1/productos -----------------------------------------------------
# Estos son de administración (alta/edición de catálogo). El catálogo que
# ve el cliente es otro conjunto de endpoints públicos, GET /api/v1/catalogo/*
# — acá todo requiere permiso de administrador, GET incluido.

productos_router = APIRouter(prefix="/api/v1/productos", tags=["productos"], dependencies=[admin_requerido])


@productos_router.get("", response_model=list[ProductoRespuesta])
def listar_productos(
    db: Session = Depends(get_db), paginacion: ParametrosPaginacion = Depends(parametros_paginacion)
) -> list[ProductoRespuesta]:
    return cu_productos.listar(db, paginacion)


@productos_router.get("/{producto_id}", response_model=ProductoRespuesta)
def obtener_producto(producto_id: int, db: Session = Depends(get_db)) -> ProductoRespuesta:
    return cu_productos.obtener(db, producto_id)


@productos_router.post("", response_model=ProductoRespuesta, status_code=status.HTTP_201_CREATED)
def crear_producto(
    datos: ProductoCrear, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> ProductoRespuesta:
    return cu_productos.crear(db, datos, creado_por=usuario.id)


@productos_router.put("/{producto_id}", response_model=ProductoRespuesta)
def actualizar_producto(
    producto_id: int, datos: ProductoActualizar, db: Session = Depends(get_db)
) -> ProductoRespuesta:
    return cu_productos.actualizar(db, producto_id, datos)


@productos_router.delete("/{producto_id}", status_code=status.HTTP_204_NO_CONTENT)
def desactivar_producto(producto_id: int, db: Session = Depends(get_db)) -> None:
    cu_productos.desactivar(db, producto_id)


# ---- /api/v1/productos/{id}/variantes y /api/v1/variantes/{id} -------------


@productos_router.get("/{producto_id}/variantes", response_model=list[VarianteRespuesta])
def listar_variantes(producto_id: int, db: Session = Depends(get_db)) -> list[VarianteRespuesta]:
    variantes = cu_productos.listar_variantes(db, producto_id)
    return [VarianteRespuesta.from_modelo(v) for v in variantes]


@productos_router.post(
    "/{producto_id}/variantes", response_model=list[VarianteRespuesta], status_code=status.HTTP_201_CREATED
)
def agregar_variantes(
    producto_id: int, datos: VariantesGenerarRequest, db: Session = Depends(get_db)
) -> list[VarianteRespuesta]:
    variantes = cu_productos.agregar_variantes(db, producto_id, datos)
    return [VarianteRespuesta.from_modelo(v) for v in variantes]


variantes_router = APIRouter(prefix="/api/v1/variantes", tags=["variantes"], dependencies=[admin_requerido])


@variantes_router.put("/{variante_id}", response_model=VarianteRespuesta)
def actualizar_variante(
    variante_id: int, datos: VarianteActualizar, db: Session = Depends(get_db)
) -> VarianteRespuesta:
    variante = cu_productos.actualizar_variante(db, variante_id, datos)
    return VarianteRespuesta.from_modelo(variante)


@variantes_router.delete("/{variante_id}", status_code=status.HTTP_204_NO_CONTENT)
def desactivar_variante(variante_id: int, db: Session = Depends(get_db)) -> None:
    cu_productos.desactivar_variante(db, variante_id)


# ---- /api/v1/productos/{id}/medidas -----------------------------------------


@productos_router.get("/{producto_id}/medidas", response_model=list[TablaMedidaRespuesta])
def listar_medidas(producto_id: int, db: Session = Depends(get_db)) -> list[TablaMedidaRespuesta]:
    return cu_productos.listar_medidas(db, producto_id)


@productos_router.post(
    "/{producto_id}/medidas", response_model=TablaMedidaRespuesta, status_code=status.HTTP_201_CREATED
)
def crear_medida(
    producto_id: int, datos: TablaMedidaCrear, db: Session = Depends(get_db)
) -> TablaMedidaRespuesta:
    return cu_productos.crear_medida(db, producto_id, datos)


@productos_router.put("/{producto_id}/medidas/{medida_id}", response_model=TablaMedidaRespuesta)
def actualizar_medida(
    producto_id: int, medida_id: int, datos: TablaMedidaActualizar, db: Session = Depends(get_db)
) -> TablaMedidaRespuesta:
    return cu_productos.actualizar_medida(db, producto_id, medida_id, datos)


@productos_router.delete("/{producto_id}/medidas/{medida_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_medida(producto_id: int, medida_id: int, db: Session = Depends(get_db)) -> None:
    cu_productos.eliminar_medida(db, producto_id, medida_id)


# ---- /api/v1/productos/{id}/imagenes y /api/v1/imagenes/{id} ---------------
# La subida pasa siempre por el backend: el cliente nunca ve el api_secret
# de Cloudinary ni sube directo. Ver core/storage.py.


@productos_router.post(
    "/{producto_id}/imagenes", response_model=ImagenRespuesta, status_code=status.HTTP_201_CREATED
)
async def subir_imagen(
    producto_id: int,
    archivo: UploadFile = File(...),
    color_id: int | None = Form(default=None),
    es_principal: bool = Form(default=False),
    db: Session = Depends(get_db),
) -> ImagenRespuesta:
    contenido = await archivo.read()
    imagen, url = cu_productos.subir_imagen(
        db, producto_id, contenido, archivo.content_type, color_id, es_principal
    )
    return ImagenRespuesta.from_modelo(imagen, url)


imagenes_router = APIRouter(prefix="/api/v1/imagenes", tags=["imagenes"], dependencies=[admin_requerido])


@imagenes_router.delete("/{imagen_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_imagen(imagen_id: int, db: Session = Depends(get_db)) -> None:
    cu_productos.eliminar_imagen(db, imagen_id)


@imagenes_router.put("/{imagen_id}/principal", response_model=ImagenRespuesta)
def marcar_imagen_principal(imagen_id: int, db: Session = Depends(get_db)) -> ImagenRespuesta:
    imagen, url = cu_productos.marcar_imagen_principal(db, imagen_id)
    return ImagenRespuesta.from_modelo(imagen, url)


# ---- /api/v1/catalogo (público) --------------------------------------------

catalogo_router = APIRouter(prefix="/api/v1/catalogo", tags=["catalogo"])


@catalogo_router.get("", response_model=list[CatalogoItemRespuesta])
@limiter.limit("60/minute")
def listar_catalogo(
    request: Request,
    db: Session = Depends(get_db),
    paginacion: ParametrosPaginacion = Depends(paginacion_catalogo),
) -> list[CatalogoItemRespuesta]:
    return cu_consultar_catalogo.listar(db, paginacion)


@catalogo_router.get("/buscar", response_model=list[CatalogoItemRespuesta])
@limiter.limit("30/minute")
def buscar_catalogo(
    request: Request,
    db: Session = Depends(get_db),
    paginacion: ParametrosPaginacion = Depends(paginacion_catalogo),
    q: str | None = Query(default=None, description="Texto libre sobre nombre y descripción"),
    categoria_id: int | None = None,
    talla_id: int | None = None,
    color_id: int | None = None,
    material_id: int | None = None,
    temporada_id: int | None = None,
    genero: Genero | None = None,
    precio_min: Decimal | None = None,
    precio_max: Decimal | None = None,
    sucursal_id: int | None = None,
    solo_disponibles: bool = False,
) -> list[CatalogoItemRespuesta]:
    filtros = FiltrosCatalogo(
        texto=q,
        categoria_id=categoria_id,
        talla_id=talla_id,
        color_id=color_id,
        material_id=material_id,
        temporada_id=temporada_id,
        genero=genero,
        precio_min=precio_min,
        precio_max=precio_max,
        sucursal_id=sucursal_id,
        solo_disponibles=solo_disponibles,
    )
    return cu_buscar_prendas.buscar(db, paginacion, filtros)


@catalogo_router.get(
    "/variantes/buscar",
    response_model=list[VarianteBusquedaRespuesta],
    dependencies=[Depends(require_permission("catalogo.ver"))],
)
def buscar_variantes_para_venta(
    q: str = Query(min_length=1, description="Código de barras exacto, sku, nombre o código de producto"),
    db: Session = Depends(get_db),
) -> list[VarianteBusquedaRespuesta]:
    filas = cu_buscar_prendas.buscar_para_venta(db, q)
    return [
        VarianteBusquedaRespuesta(
            variante_id=variante.id,
            producto_id=producto.id,
            producto_nombre=producto.nombre,
            producto_codigo=producto.codigo,
            talla_codigo=talla.codigo,
            color_nombre=color.nombre,
            sku=variante.sku,
            codigo_barras=variante.codigo_barras,
            precio_efectivo=variante.precio if variante.precio is not None else producto.precio_base,
        )
        for variante, producto, talla, color in filas
    ]


@catalogo_router.get("/variantes/detalle", response_model=list[ProductoImagenLookupItem])
def obtener_detalle_para_dashboard(
    variante_ids: str | None = Query(default=None, description="IDs de variante separados por coma"),
    producto_ids: str | None = Query(default=None, description="IDs de producto separados por coma"),
    db: Session = Depends(get_db),
    usuario=Depends(get_current_user),
) -> list[ProductoImagenLookupItem]:
    v_ids = [int(x) for x in variante_ids.split(",") if x] if variante_ids else None
    p_ids = [int(x) for x in producto_ids.split(",") if x] if producto_ids else None
    return cu_consultar_catalogo.resolver_imagen_lookup(db, v_ids, p_ids)


@catalogo_router.get("/{producto_id}", response_model=CatalogoDetalleRespuesta)
def obtener_detalle_catalogo(
    producto_id: int,
    sucursal_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
) -> CatalogoDetalleRespuesta:
    return cu_consultar_catalogo.obtener_detalle(db, producto_id, sucursal_id)


# ---- /api/v1/favoritos (requiere sesión de cliente) -------------------------

favoritos_router = APIRouter(prefix="/api/v1/favoritos", tags=["favoritos"])


@favoritos_router.get("", response_model=list[FavoritoRespuesta])
def listar_favoritos(
    usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> list[FavoritoRespuesta]:
    return cu_favoritos.listar(db, usuario.id)


@favoritos_router.post("", response_model=FavoritoRespuesta, status_code=status.HTTP_201_CREATED)
def agregar_favorito(
    datos: FavoritoCrear, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> FavoritoRespuesta:
    return cu_favoritos.agregar(db, usuario.id, datos.variante_id)


@favoritos_router.delete("/{variante_id}", status_code=status.HTTP_204_NO_CONTENT)
def quitar_favorito(
    variante_id: int, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> None:
    cu_favoritos.quitar(db, usuario.id, variante_id)


routers = [
    categorias_router,
    tallas_router,
    colores_router,
    materiales_router,
    temporadas_router,
    colecciones_router,
    productos_router,
    variantes_router,
    imagenes_router,
    catalogo_router,
    favoritos_router,
]
