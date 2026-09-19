from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.abastecimiento.casos_uso.cu11_gestionar_proveedores import GestionarProveedores
from app.abastecimiento.casos_uso.cu12_registrar_recepcion_mercaderia import RegistrarRecepcionMercaderia
from app.abastecimiento.schemas import (
    OrdenCompraActualizar,
    OrdenCompraCrear,
    OrdenCompraRespuesta,
    ProductoProveedorCrear,
    ProductoProveedorRespuesta,
    ProveedorActualizar,
    ProveedorCrear,
    ProveedorRespuesta,
    RecepcionCrear,
    RecepcionRespuesta,
)
from app.core.database import get_db
from app.core.deps import ParametrosPaginacion, parametros_paginacion
from app.core.security import get_current_user, require_permission

PERMISO_ABASTECIMIENTO = "abastecimiento.gestionar"
admin_requerido = Depends(require_permission(PERMISO_ABASTECIMIENTO))

cu_gestionar_proveedores = GestionarProveedores()
cu_registrar_recepcion = RegistrarRecepcionMercaderia()

# ---- /api/v1/proveedores -------------------------------------------------------

proveedores_router = APIRouter(
    prefix="/api/v1/proveedores", tags=["proveedores"], dependencies=[admin_requerido]
)


@proveedores_router.get("", response_model=list[ProveedorRespuesta])
def listar_proveedores(
    db: Session = Depends(get_db), paginacion: ParametrosPaginacion = Depends(parametros_paginacion)
) -> list[ProveedorRespuesta]:
    return cu_gestionar_proveedores.listar(db, paginacion)


@proveedores_router.get("/{proveedor_id}", response_model=ProveedorRespuesta)
def obtener_proveedor(proveedor_id: int, db: Session = Depends(get_db)) -> ProveedorRespuesta:
    return cu_gestionar_proveedores.obtener(db, proveedor_id)


@proveedores_router.post("", response_model=ProveedorRespuesta, status_code=status.HTTP_201_CREATED)
def crear_proveedor(datos: ProveedorCrear, db: Session = Depends(get_db)) -> ProveedorRespuesta:
    return cu_gestionar_proveedores.crear(db, datos)


@proveedores_router.put("/{proveedor_id}", response_model=ProveedorRespuesta)
def actualizar_proveedor(
    proveedor_id: int, datos: ProveedorActualizar, db: Session = Depends(get_db)
) -> ProveedorRespuesta:
    return cu_gestionar_proveedores.actualizar(db, proveedor_id, datos)


@proveedores_router.delete("/{proveedor_id}", status_code=status.HTTP_204_NO_CONTENT)
def desactivar_proveedor(proveedor_id: int, db: Session = Depends(get_db)) -> None:
    cu_gestionar_proveedores.desactivar(db, proveedor_id)


# ---- /api/v1/proveedores/{id}/productos ----------------------------------------

productos_proveedor_router = APIRouter(
    prefix="/api/v1/proveedores/{proveedor_id}/productos", tags=["proveedores"], dependencies=[admin_requerido]
)


@productos_proveedor_router.get("", response_model=list[ProductoProveedorRespuesta])
def listar_productos_proveedor(proveedor_id: int, db: Session = Depends(get_db)) -> list[ProductoProveedorRespuesta]:
    return cu_gestionar_proveedores.listar_productos(db, proveedor_id)


@productos_proveedor_router.post(
    "", response_model=ProductoProveedorRespuesta, status_code=status.HTTP_201_CREATED
)
def agregar_producto_proveedor(
    proveedor_id: int, datos: ProductoProveedorCrear, db: Session = Depends(get_db)
) -> ProductoProveedorRespuesta:
    return cu_gestionar_proveedores.agregar_producto(
        db, proveedor_id, datos.producto_id, datos.costo_referencial, datos.dias_entrega
    )


@productos_proveedor_router.delete("/{producto_id}", status_code=status.HTTP_204_NO_CONTENT)
def quitar_producto_proveedor(proveedor_id: int, producto_id: int, db: Session = Depends(get_db)) -> None:
    cu_gestionar_proveedores.quitar_producto(db, proveedor_id, producto_id)


# ---- /api/v1/ordenes-compra -----------------------------------------------------
# OrdenCompra es soporte de CU-12 (ver docstring del caso de uso), no un CU
# propio del catálogo de 43.

ordenes_compra_router = APIRouter(
    prefix="/api/v1/ordenes-compra", tags=["ordenes-compra"], dependencies=[admin_requerido]
)


@ordenes_compra_router.get("", response_model=list[OrdenCompraRespuesta])
def listar_ordenes_compra(
    proveedor_id: int | None = None, sucursal_id: int | None = None, db: Session = Depends(get_db)
) -> list[OrdenCompraRespuesta]:
    return list(cu_registrar_recepcion.ordenes_compra.listar(db, proveedor_id, sucursal_id))


@ordenes_compra_router.get("/{orden_id}", response_model=OrdenCompraRespuesta)
def obtener_orden_compra(orden_id: int, db: Session = Depends(get_db)) -> OrdenCompraRespuesta:
    return cu_registrar_recepcion.ordenes_compra.obtener(db, orden_id)


@ordenes_compra_router.post("", response_model=OrdenCompraRespuesta, status_code=status.HTTP_201_CREATED)
def crear_orden_compra(
    datos: OrdenCompraCrear, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> OrdenCompraRespuesta:
    return cu_registrar_recepcion.ordenes_compra.crear(db, datos, usuario.id)


@ordenes_compra_router.put("/{orden_id}", response_model=OrdenCompraRespuesta)
def actualizar_orden_compra(
    orden_id: int, datos: OrdenCompraActualizar, db: Session = Depends(get_db)
) -> OrdenCompraRespuesta:
    return cu_registrar_recepcion.ordenes_compra.actualizar(db, orden_id, datos)


@ordenes_compra_router.post("/{orden_id}/enviar", response_model=OrdenCompraRespuesta)
def enviar_orden_compra(orden_id: int, db: Session = Depends(get_db)) -> OrdenCompraRespuesta:
    return cu_registrar_recepcion.ordenes_compra.enviar(db, orden_id)


@ordenes_compra_router.delete("/{orden_id}", response_model=OrdenCompraRespuesta)
def anular_orden_compra(orden_id: int, db: Session = Depends(get_db)) -> OrdenCompraRespuesta:
    return cu_registrar_recepcion.ordenes_compra.anular(db, orden_id)


# ---- /api/v1/recepciones ---------------------------------------------------------

recepciones_router = APIRouter(
    prefix="/api/v1/recepciones", tags=["recepciones"], dependencies=[admin_requerido]
)


@recepciones_router.get("", response_model=list[RecepcionRespuesta])
def listar_recepciones(orden_compra_id: int | None = None, db: Session = Depends(get_db)) -> list[RecepcionRespuesta]:
    return list(cu_registrar_recepcion.listar(db, orden_compra_id))


@recepciones_router.get("/{recepcion_id}", response_model=RecepcionRespuesta)
def obtener_recepcion(recepcion_id: int, db: Session = Depends(get_db)) -> RecepcionRespuesta:
    return cu_registrar_recepcion.obtener(db, recepcion_id)


@recepciones_router.post("", response_model=RecepcionRespuesta, status_code=status.HTTP_201_CREATED)
def crear_recepcion(
    datos: RecepcionCrear, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> RecepcionRespuesta:
    return cu_registrar_recepcion.registrar(db, datos, empleado_id=None, creado_por=usuario.id)


routers = [proveedores_router, productos_proveedor_router, ordenes_compra_router, recepciones_router]
