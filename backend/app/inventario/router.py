from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user, require_permission
from app.inventario.casos_uso.cu13_consultar_disponibilidad_sucursal import ConsultarDisponibilidadSucursal
from app.inventario.casos_uso.cu14_consultar_inventario_global import ConsultarInventarioGlobal
from app.inventario.casos_uso.cu15_registrar_movimiento_inventario import RegistrarMovimientoInventario
from app.inventario.schemas import (
    AjusteCrear,
    ConsolidadoRespuesta,
    DisponibilidadRespuesta,
    LimitesActualizar,
    MovimientoCrear,
    MovimientoRespuesta,
    StockRespuesta,
    TipoMovimientoRespuesta,
    TransferenciaCrear,
    TransferenciaRespuesta,
    ValuacionRespuesta,
)

PERMISO_VER = "inventario.ver"
PERMISO_GESTIONAR = "inventario.gestionar"
ver_requerido = Depends(require_permission(PERMISO_VER))
gestionar_requerido = Depends(require_permission(PERMISO_GESTIONAR))

cu_consultar_disponibilidad = ConsultarDisponibilidadSucursal()
cu_consultar_inventario = ConsultarInventarioGlobal()
cu_registrar_movimiento = RegistrarMovimientoInventario()


# ---- /api/v1/inventario/disponibilidad (público) -----------------------------
# Lo consume el catálogo/detalle para mostrar disponibilidad por sucursal.
# Vive separado del resto (sin `ver_requerido`) porque cualquiera lo puede
# consultar, igual que /api/v1/catalogo.

publico_router = APIRouter(prefix="/api/v1/inventario", tags=["inventario"])


@publico_router.get("/disponibilidad", response_model=list[DisponibilidadRespuesta])
def consultar_disponibilidad(
    variante_id: int = Query(...),
    sucursal_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[DisponibilidadRespuesta]:
    return list(cu_consultar_disponibilidad.ejecutar(db, variante_id, sucursal_id))


# ---- /api/v1/inventario (administración) --------------------------------------

router = APIRouter(prefix="/api/v1/inventario", tags=["inventario"], dependencies=[ver_requerido])


@router.get("/tipos-movimiento", response_model=list[TipoMovimientoRespuesta])
def listar_tipos_movimiento(db: Session = Depends(get_db)) -> list[TipoMovimientoRespuesta]:
    return list(cu_registrar_movimiento.listar_tipos_movimiento(db))


@router.get("/consolidado", response_model=list[ConsolidadoRespuesta])
def listar_consolidado(
    sucursal_id: int | None = Query(default=None),
    producto_id: int | None = Query(default=None),
    usuario=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ConsolidadoRespuesta]:
    filas = cu_consultar_inventario.listar_consolidado(db, usuario.id, sucursal_id, producto_id)
    return [ConsolidadoRespuesta(**fila) for fila in filas]


@router.get("/alertas", response_model=list[ConsolidadoRespuesta])
def listar_alertas(
    sucursal_id: int | None = Query(default=None), usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> list[ConsolidadoRespuesta]:
    return [ConsolidadoRespuesta(**fila) for fila in cu_consultar_inventario.listar_alertas(db, usuario.id, sucursal_id)]


@router.get("/valuacion", response_model=list[ValuacionRespuesta])
def listar_valuacion(
    sucursal_id: int | None = Query(default=None), usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> list[ValuacionRespuesta]:
    return [ValuacionRespuesta(**fila) for fila in cu_consultar_inventario.listar_valuacion(db, usuario.id, sucursal_id)]


@router.get("/sucursal/{sucursal_id}", response_model=list[StockRespuesta])
def listar_stock_por_sucursal(
    sucursal_id: int, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> list[StockRespuesta]:
    return list(cu_consultar_inventario.listar_stock_por_sucursal(db, usuario.id, sucursal_id))


@router.get("/stock/{variante_id}/{sucursal_id}", response_model=StockRespuesta)
def obtener_stock(
    variante_id: int, sucursal_id: int, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> StockRespuesta:
    return cu_consultar_inventario.obtener_stock(db, usuario.id, variante_id, sucursal_id)


@router.get("/stock", response_model=list[StockRespuesta])
def listar_stock_por_variante(
    variante_id: int = Query(...), usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> list[StockRespuesta]:
    return list(cu_consultar_inventario.listar_stock_por_variante(db, usuario.id, variante_id))


@router.put("/stock/{stock_id}/limites", response_model=StockRespuesta, dependencies=[gestionar_requerido])
def actualizar_limites_stock(
    stock_id: int, datos: LimitesActualizar, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> StockRespuesta:
    return cu_consultar_inventario.actualizar_limites(db, usuario.id, stock_id, datos.stock_minimo, datos.stock_maximo)


@router.get("/movimientos", response_model=list[MovimientoRespuesta])
def listar_kardex(
    variante_id: int = Query(...),
    sucursal_id: int = Query(...),
    usuario=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[MovimientoRespuesta]:
    movimientos = cu_registrar_movimiento.listar_kardex(db, usuario.id, variante_id, sucursal_id)
    codigos = cu_registrar_movimiento.mapa_codigos_tipo_movimiento(db)
    return [MovimientoRespuesta.from_modelo(m, codigos[m.tipo_movimiento_id]) for m in movimientos]


@router.post(
    "/movimientos",
    response_model=MovimientoRespuesta,
    status_code=status.HTTP_201_CREATED,
    dependencies=[gestionar_requerido],
)
def registrar_movimiento(
    datos: MovimientoCrear, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> MovimientoRespuesta:
    movimiento = cu_registrar_movimiento.registrar_movimiento(db, usuario.id, datos)
    # actualizar_stock_operacion ya validó que el código exista (si no,
    # hubiera lanzado antes de llegar acá): se reusa el mismo valor en vez
    # de volver a consultar `tipo_movimiento` desde el router.
    return MovimientoRespuesta.from_modelo(movimiento, datos.tipo_movimiento_codigo)


# Sin POST /reservas ni /liberaciones sueltos: reservar_stock/liberar_stock
# son pasos internos de reservas (CU-16/18/20) y ventas (CU-24/25). Moverlos
# a mano desincronizaba cantidad_reservada de las reservas reales y trababa
# su expiración automática.


@router.post(
    "/ajustes", response_model=MovimientoRespuesta, status_code=status.HTTP_201_CREATED, dependencies=[gestionar_requerido]
)
def registrar_ajuste(
    datos: AjusteCrear, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> MovimientoRespuesta:
    movimiento = cu_registrar_movimiento.registrar_ajuste(
        db, datos.variante_id, datos.sucursal_id, datos.cantidad, usuario.id, datos.observacion
    )
    codigo = "ajuste_positivo" if datos.cantidad > 0 else "ajuste_negativo"
    return MovimientoRespuesta.from_modelo(movimiento, codigo)


# ---- /api/v1/transferencias ----------------------------------------------------
# Recurso propio (no cuelga de /inventario en la URL) pero vive en este
# paquete: transferencia/transferencia_detalle son tablas de inventario.

transferencias_router = APIRouter(
    prefix="/api/v1/transferencias", tags=["transferencias"], dependencies=[ver_requerido]
)


@transferencias_router.get("", response_model=list[TransferenciaRespuesta])
def listar_transferencias(
    sucursal_id: int | None = Query(default=None), usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> list[TransferenciaRespuesta]:
    return list(cu_registrar_movimiento.listar_transferencias(db, usuario.id, sucursal_id))


@transferencias_router.get("/{transferencia_id}", response_model=TransferenciaRespuesta)
def obtener_transferencia(
    transferencia_id: int, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> TransferenciaRespuesta:
    return cu_registrar_movimiento.obtener_transferencia(db, usuario.id, transferencia_id)


@transferencias_router.post(
    "", response_model=TransferenciaRespuesta, status_code=status.HTTP_201_CREATED, dependencies=[gestionar_requerido]
)
def crear_transferencia(
    datos: TransferenciaCrear, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> TransferenciaRespuesta:
    return cu_registrar_movimiento.crear_transferencia(db, datos, usuario.id)


@transferencias_router.post(
    "/{transferencia_id}/enviar", response_model=TransferenciaRespuesta, dependencies=[gestionar_requerido]
)
def enviar_transferencia(
    transferencia_id: int, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> TransferenciaRespuesta:
    return cu_registrar_movimiento.enviar_transferencia(db, transferencia_id, usuario.id)


@transferencias_router.post(
    "/{transferencia_id}/recibir", response_model=TransferenciaRespuesta, dependencies=[gestionar_requerido]
)
def recibir_transferencia(
    transferencia_id: int, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> TransferenciaRespuesta:
    return cu_registrar_movimiento.recibir_transferencia(db, transferencia_id, usuario.id)


@transferencias_router.delete(
    "/{transferencia_id}", status_code=status.HTTP_200_OK, response_model=TransferenciaRespuesta, dependencies=[gestionar_requerido]
)
def anular_transferencia(
    transferencia_id: int, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> TransferenciaRespuesta:
    return cu_registrar_movimiento.anular_transferencia(db, usuario.id, transferencia_id)


routers = [publico_router, router, transferencias_router]
