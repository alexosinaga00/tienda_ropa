from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.comercial.casos_uso.cu12_gestionar_reservas import (
    AtenderPruebaReservaSucursal,
    CancelarReserva,
    ConsultarEstadoReserva,
    ConsultarReservasSucursal,
    ReservarPrendas,
)
from app.comercial.casos_uso.cu13_gestionar_carrito_compra_digital import (
    GestionarCarrito,
    RealizarCompraDigital,
    RealizarPedidoDiferido,
)
from app.comercial.casos_uso.cu14_registrar_venta_presencial import RegistrarVentaPresencial
from app.comercial.casos_uso.cu15_consultar_ventas import ConsultarHistorialCompras, ConsultarVentasSucursal
from app.comercial.casos_uso.cu16_gestionar_promociones import GestionarPromociones
from app.comercial.casos_uso.cu17_gestionar_devoluciones_cambios import (
    ConsultarPlazoCambio,
    ConsultarSolicitudesCambio,
    RegistrarDevolucion,
    ResolverSolicitudCambio,
    SolicitarCambio,
)
from app.comercial.casos_uso.cu18_procesar_pagos import (
    ConfirmarRechazarTransaccion,
    GestionarMetodoPagoGuardado,
    PagarPasarelaDigital,
    ProcesarPagoCaja,
)
from app.comercial.casos_uso.cu19_gestionar_envios_tarifas import (
    ActualizarEstadoEnvio,
    GestionarZonasTarifas,
    SolicitarEnvioDomicilio,
)
from app.comercial.politicas import (
    construir_pago_respuesta,
    expirar_reservas_de_todas_las_empresas,
    expirar_ventas_de_todas_las_empresas,
    mapa_codigos_estado_reserva,
    mapa_codigos_estado_venta,
    devuelto_por_venta_y_linea,
)
from app.comercial.schemas import (
    CarritoDetalleActualizar,
    CarritoDetalleCrear,
    CarritoRespuesta,
    CarritoResumenRespuesta,
    CotizarEnvioRequest,
    CotizarEnvioRespuesta,
    DevolucionCrear,
    DevolucionRespuesta,
    DireccionClienteActualizar,
    DireccionClienteCrear,
    DireccionClienteRespuesta,
    EnvioCrear,
    EnvioEstadoActualizar,
    EnvioRespuesta,
    EstadoEnvio,
    MetodoPagoPayPalConfirmar,
    MetodoPagoPayPalIniciar,
    MetodoPagoPayPalIniciarRespuesta,
    MetodoPagoPayPalRespuesta,
    PagoCajaRequest,
    PagoCajaRespuesta,
    PagoIniciarRequest,
    PagoIniciarRespuesta,
    PagoRespuesta,
    PedidoDiferidoCrear,
    PedidoDiferidoRespuesta,
    PlazoCambioRespuesta,
    PromocionActualizar,
    PromocionCrear,
    PromocionRespuesta,
    ReservaCrear,
    ReservaRespuesta,
    SeleccionActualizar,
    SolicitudCambioCrear,
    SolicitudCambioRechazar,
    SolicitudCambioRespuesta,
    VentaDigitalCrear,
    VentaPresencialCrear,
    VentaRespuesta,
    ZonaEnvioActualizar,
    ZonaEnvioCrear,
    ZonaEnvioRespuesta,
)
from app.core.auditoria import ContextoAuditoria, obtener_contexto_auditoria
from app.core.database import get_db
from app.core.deps import ParametrosPaginacion, parametros_paginacion
from app.core.permisos import (
    PERMISO_ENTREGAS,
    PERMISO_PAGOS,
    PERMISO_RESERVAS_CREAR,
    PERMISO_STAFF_RESERVAS,
    PERMISO_STAFF_VENTAS,
    PERMISO_VENTAS_DIGITAL,
    PERMISO_VENTAS_GESTIONAR,
    PERMISO_VENTAS_PRESENCIAL,
)
from app.core.planes import FUNC_GESTION_VENTAS, FUNC_RESERVAS, exigir_funcionalidad
from app.core.security import get_current_user, require_permission, require_service_token

# Compuertas del plan. Van SIEMPRE antes que las dependencias de permiso en la
# lista `dependencies=` (orden de errores: 401 -> suscripcion_no_activa ->
# plan_no_incluye_funcionalidad -> falta el permiso). Las de router se
# resuelven antes que las de ruta, así que cumplen el orden sin repetirse.
plan_reservas = Depends(exigir_funcionalidad(FUNC_RESERVAS))
plan_gestion_ventas = Depends(exigir_funcionalidad(FUNC_GESTION_VENTAS))


# ---- Reservas ----


crear_requerido = Depends(require_permission(PERMISO_RESERVAS_CREAR))
staff_reservas_requerido = Depends(require_permission(PERMISO_STAFF_RESERVAS))

cu_reservar_prendas = ReservarPrendas()
cu_consultar_estado = ConsultarEstadoReserva()
cu_cancelar_reserva = CancelarReserva()
cu_consultar_sucursal = ConsultarReservasSucursal()
cu_atender_prueba = AtenderPruebaReservaSucursal()


def _respuesta(db: Session, reserva) -> ReservaRespuesta:
    return ReservaRespuesta.from_modelo(reserva, mapa_codigos_estado_reserva(db))


reservas_router = APIRouter(prefix="/api/v1/reservas", tags=["reservas"], dependencies=[plan_reservas])


@reservas_router.post("", response_model=ReservaRespuesta, status_code=status.HTTP_201_CREATED, dependencies=[crear_requerido])
def crear_reserva(
    datos: ReservaCrear, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> ReservaRespuesta:
    reserva = cu_reservar_prendas.ejecutar(db, usuario.id, datos)
    return _respuesta(db, reserva)


@reservas_router.get("/mis-reservas", response_model=list[ReservaRespuesta], dependencies=[crear_requerido])
def listar_mis_reservas(usuario=Depends(get_current_user), db: Session = Depends(get_db)) -> list[ReservaRespuesta]:
    estados = mapa_codigos_estado_reserva(db)
    return [ReservaRespuesta.from_modelo(r, estados) for r in cu_consultar_estado.listar_mias(db, usuario.id)]


@reservas_router.get("/sucursal/{sucursal_id}", response_model=list[ReservaRespuesta], dependencies=[staff_reservas_requerido])
def listar_reservas_sucursal(
    sucursal_id: int, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> list[ReservaRespuesta]:
    estados = mapa_codigos_estado_reserva(db)
    reservas = cu_consultar_sucursal.ejecutar(db, sucursal_id, usuario.id)
    return [ReservaRespuesta.from_modelo(r, estados) for r in reservas]


@reservas_router.get("/{reserva_id}", response_model=ReservaRespuesta)
def obtener_reserva(
    reserva_id: int, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> ReservaRespuesta:
    reserva = cu_consultar_estado.obtener(db, reserva_id, usuario.id)
    return _respuesta(db, reserva)


@reservas_router.delete("/{reserva_id}", response_model=ReservaRespuesta)
def cancelar_reserva(
    reserva_id: int, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> ReservaRespuesta:
    reserva = cu_cancelar_reserva.ejecutar(db, reserva_id, usuario.id)
    return _respuesta(db, reserva)


@reservas_router.put("/{reserva_id}/preparar", response_model=ReservaRespuesta, dependencies=[staff_reservas_requerido])
def preparar_reserva(
    reserva_id: int, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> ReservaRespuesta:
    reserva = cu_atender_prueba.preparar(db, reserva_id, usuario.id)
    return _respuesta(db, reserva)


@reservas_router.put("/{reserva_id}/confirmar-llegada", response_model=ReservaRespuesta, dependencies=[staff_reservas_requerido])
def confirmar_llegada(
    reserva_id: int, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> ReservaRespuesta:
    reserva = cu_atender_prueba.confirmar_llegada(db, reserva_id, usuario.id)
    return _respuesta(db, reserva)


@reservas_router.put("/{reserva_id}/seleccion", response_model=ReservaRespuesta, dependencies=[staff_reservas_requerido])
def registrar_seleccion(
    reserva_id: int, datos: SeleccionActualizar, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> ReservaRespuesta:
    reserva = cu_atender_prueba.registrar_seleccion(db, reserva_id, usuario.id, datos)
    return _respuesta(db, reserva)


# ---- /api/v1/tareas ---------------------------------------------------------------
# Protegida por token de servicio (no por JWT): la dispara un cron/scheduler,
# no una persona logueada. expirar_reservas_vencidas no es un caso de uso
# del catálogo (no tiene actor humano): vive en comercial/politicas.py.

tareas_reservas_router = APIRouter(prefix="/api/v1/tareas", tags=["tareas"], dependencies=[Depends(require_service_token)])


@tareas_reservas_router.post("/expirar-reservas")
def expirar_reservas(db: Session = Depends(get_db)) -> dict:
    cantidad = expirar_reservas_de_todas_las_empresas(db)
    return {"expiradas": cantidad}


_routers_reservas = [reservas_router, tareas_reservas_router]


# ---- Ventas ----


digital_requerido = Depends(require_permission(PERMISO_VENTAS_DIGITAL))
presencial_requerido = Depends(require_permission(PERMISO_VENTAS_PRESENCIAL))
staff_ventas_requerido = Depends(require_permission(PERMISO_STAFF_VENTAS))
gestionar_ventas_requerido = Depends(require_permission(PERMISO_VENTAS_GESTIONAR))

cu_gestionar_carrito = GestionarCarrito()
cu_compra_digital = RealizarCompraDigital()
cu_venta_presencial = RegistrarVentaPresencial()
cu_historial_compras = ConsultarHistorialCompras()
cu_gestionar_promociones = GestionarPromociones()
cu_ventas_sucursal = ConsultarVentasSucursal()
cu_registrar_devolucion = RegistrarDevolucion()
cu_plazo_cambio = ConsultarPlazoCambio()
cu_solicitar_cambio = SolicitarCambio()
cu_resolver_solicitud = ResolverSolicitudCambio()
cu_consultar_solicitudes = ConsultarSolicitudesCambio()
cu_metodo_pago_guardado = GestionarMetodoPagoGuardado()
cu_pedido_diferido = RealizarPedidoDiferido()


def _venta_respuesta(db: Session, venta) -> VentaRespuesta:
    return _ventas_respuesta(db, [venta])[0]


def _ventas_respuesta(db: Session, ventas: list) -> list[VentaRespuesta]:
    """Una lista de ventas con su estado y lo devuelto de cada una y de cada línea (una sola consulta para todas)."""
    estados = mapa_codigos_estado_venta(db)
    por_venta, por_linea = devuelto_por_venta_y_linea(db, ventas)
    return [VentaRespuesta.from_modelo(v, estados, por_venta.get(v.id, 0), por_linea) for v in ventas]


# ---- /api/v1/carrito ---------------------------------------------------------------

carrito_router = APIRouter(
    prefix="/api/v1/carrito", tags=["carrito"], dependencies=[plan_gestion_ventas, digital_requerido]
)


@carrito_router.get("", response_model=CarritoRespuesta)
def obtener_mi_carrito(usuario=Depends(get_current_user), db: Session = Depends(get_db)) -> CarritoRespuesta:
    return cu_gestionar_carrito.obtener_mi_carrito(db, usuario.id)


@carrito_router.post("", response_model=CarritoRespuesta, status_code=status.HTTP_201_CREATED)
def agregar_al_carrito(
    datos: CarritoDetalleCrear, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> CarritoRespuesta:
    return cu_gestionar_carrito.agregar(db, usuario.id, datos)


@carrito_router.put("/{variante_id}", response_model=CarritoRespuesta)
def actualizar_linea_carrito(
    variante_id: int,
    datos: CarritoDetalleActualizar,
    usuario=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CarritoRespuesta:
    return cu_gestionar_carrito.actualizar_linea(db, usuario.id, variante_id, datos)


@carrito_router.delete("/{variante_id}", response_model=CarritoRespuesta)
def quitar_del_carrito(
    variante_id: int, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> CarritoRespuesta:
    return cu_gestionar_carrito.quitar(db, usuario.id, variante_id)


@carrito_router.post("/aplicar-promocion", response_model=CarritoResumenRespuesta)
def aplicar_promocion(usuario=Depends(get_current_user), db: Session = Depends(get_db)) -> CarritoResumenRespuesta:
    return cu_gestionar_carrito.previsualizar(db, usuario.id)


# ---- /api/v1/ventas -----------------------------------------------------------------

ventas_router = APIRouter(prefix="/api/v1/ventas", tags=["ventas"], dependencies=[plan_gestion_ventas])


@ventas_router.post(
    "/digital", response_model=VentaRespuesta, status_code=status.HTTP_201_CREATED, dependencies=[digital_requerido]
)
def registrar_venta_digital(
    datos: VentaDigitalCrear, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> VentaRespuesta:
    venta = cu_compra_digital.ejecutar(db, usuario.id, datos)
    return _venta_respuesta(db, venta)


@ventas_router.post(
    "/presencial",
    response_model=VentaRespuesta,
    status_code=status.HTTP_201_CREATED,
    dependencies=[presencial_requerido],
)
def registrar_venta_presencial(
    datos: VentaPresencialCrear, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> VentaRespuesta:
    venta = cu_venta_presencial.ejecutar(db, usuario.id, datos)
    return _venta_respuesta(db, venta)


@ventas_router.get("/mis-compras", response_model=list[VentaRespuesta])
def listar_mis_compras(usuario=Depends(get_current_user), db: Session = Depends(get_db)) -> list[VentaRespuesta]:
    return _ventas_respuesta(db, cu_historial_compras.listar_mis_compras(db, usuario.id))


@ventas_router.get("/sucursal/{sucursal_id}", response_model=list[VentaRespuesta], dependencies=[staff_ventas_requerido])
def listar_ventas_sucursal(
    sucursal_id: int, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> list[VentaRespuesta]:
    return _ventas_respuesta(db, cu_ventas_sucursal.ejecutar(db, sucursal_id, usuario.id))


@ventas_router.get("/{venta_id}/comprobante", response_model=VentaRespuesta)
def obtener_comprobante(
    venta_id: int, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> VentaRespuesta:
    venta = cu_historial_compras.obtener_comprobante(db, venta_id, usuario.id)
    return _venta_respuesta(db, venta)


@ventas_router.get("/{venta_id}/plazo-cambio", response_model=PlazoCambioRespuesta)
def obtener_plazo_cambio(
    venta_id: int, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> PlazoCambioRespuesta:
    return PlazoCambioRespuesta(**cu_plazo_cambio.ejecutar(db, venta_id, usuario.id))


# ---- /api/v1/devoluciones ------------------------------------------------------------

devoluciones_router = APIRouter(
    prefix="/api/v1/devoluciones", tags=["devoluciones"], dependencies=[plan_gestion_ventas, staff_ventas_requerido]
)


@devoluciones_router.post("", response_model=DevolucionRespuesta, status_code=status.HTTP_201_CREATED)
def registrar_devolucion(
    datos: DevolucionCrear,
    segundo_plano: BackgroundTasks,
    usuario=Depends(get_current_user),
    db: Session = Depends(get_db),
    contexto: ContextoAuditoria = Depends(obtener_contexto_auditoria),
) -> DevolucionRespuesta:
    # El comprobante por correo sale después de responder (segundo plano).
    return cu_registrar_devolucion.ejecutar(db, usuario.id, datos, contexto, segundo_plano.add_task)


# ---- /api/v1/solicitudes-cambio ------------------------------------------------------
# Etapa 2 del CU-17: el cliente pide cambiar la talla o el color de una prenda de su compra y el personal de la
# sucursal la aprueba o la rechaza cuando el cliente trae la prenda.

solicitudes_cambio_router = APIRouter(
    prefix="/api/v1/solicitudes-cambio", tags=["solicitudes de cambio"], dependencies=[plan_gestion_ventas]
)


@solicitudes_cambio_router.post(
    "", response_model=SolicitudCambioRespuesta, status_code=status.HTTP_201_CREATED, dependencies=[digital_requerido]
)
def solicitar_cambio(
    datos: SolicitudCambioCrear,
    segundo_plano: BackgroundTasks,
    usuario=Depends(get_current_user),
    db: Session = Depends(get_db),
    contexto: ContextoAuditoria = Depends(obtener_contexto_auditoria),
) -> SolicitudCambioRespuesta:
    return cu_solicitar_cambio.solicitar(db, usuario.id, datos, contexto, segundo_plano.add_task)


@solicitudes_cambio_router.get("/mias", response_model=list[SolicitudCambioRespuesta], dependencies=[digital_requerido])
def listar_mis_solicitudes_cambio(
    venta_id: int | None = None, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> list[SolicitudCambioRespuesta]:
    return cu_consultar_solicitudes.listar_mias(db, usuario.id, venta_id)


@solicitudes_cambio_router.post(
    "/{solicitud_id}/cancelar", response_model=SolicitudCambioRespuesta, dependencies=[digital_requerido]
)
def cancelar_solicitud_cambio(
    solicitud_id: int,
    usuario=Depends(get_current_user),
    db: Session = Depends(get_db),
    contexto: ContextoAuditoria = Depends(obtener_contexto_auditoria),
) -> SolicitudCambioRespuesta:
    return cu_solicitar_cambio.cancelar(db, usuario.id, solicitud_id, contexto)


@solicitudes_cambio_router.get(
    "/sucursal/{sucursal_id}", response_model=list[SolicitudCambioRespuesta], dependencies=[staff_ventas_requerido]
)
def listar_solicitudes_cambio_sucursal(
    sucursal_id: int,
    estado: Literal["pendiente", "aprobada", "rechazada", "cancelada", "vencida", "todas"] = "pendiente",
    usuario=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[SolicitudCambioRespuesta]:
    return cu_consultar_solicitudes.listar_sucursal(db, usuario.id, sucursal_id, estado)


@solicitudes_cambio_router.post(
    "/{solicitud_id}/aprobar", response_model=SolicitudCambioRespuesta, dependencies=[staff_ventas_requerido]
)
def aprobar_solicitud_cambio(
    solicitud_id: int,
    segundo_plano: BackgroundTasks,
    usuario=Depends(get_current_user),
    db: Session = Depends(get_db),
    contexto: ContextoAuditoria = Depends(obtener_contexto_auditoria),
) -> SolicitudCambioRespuesta:
    # El comprobante por correo sale después de responder (segundo plano).
    return cu_resolver_solicitud.aprobar(db, usuario.id, solicitud_id, contexto, segundo_plano.add_task)


@solicitudes_cambio_router.post(
    "/{solicitud_id}/rechazar", response_model=SolicitudCambioRespuesta, dependencies=[staff_ventas_requerido]
)
def rechazar_solicitud_cambio(
    solicitud_id: int,
    datos: SolicitudCambioRechazar,
    segundo_plano: BackgroundTasks,
    usuario=Depends(get_current_user),
    db: Session = Depends(get_db),
    contexto: ContextoAuditoria = Depends(obtener_contexto_auditoria),
) -> SolicitudCambioRespuesta:
    return cu_resolver_solicitud.rechazar(db, usuario.id, solicitud_id, datos, contexto, segundo_plano.add_task)


# ---- /api/v1/promociones -------------------------------------------------------------

promociones_router = APIRouter(prefix="/api/v1/promociones", tags=["promociones"], dependencies=[plan_gestion_ventas])


@promociones_router.get("", response_model=list[PromocionRespuesta])
def listar_promociones(
    db: Session = Depends(get_db),
    paginacion: ParametrosPaginacion = Depends(parametros_paginacion),
    usuario=Depends(get_current_user),
) -> list[PromocionRespuesta]:
    return cu_gestionar_promociones.listar(db, paginacion)


@promociones_router.get("/{promocion_id}", response_model=PromocionRespuesta)
def obtener_promocion(
    promocion_id: int, db: Session = Depends(get_db), usuario=Depends(get_current_user)
) -> PromocionRespuesta:
    return cu_gestionar_promociones.obtener(db, promocion_id)


@promociones_router.post(
    "", response_model=PromocionRespuesta, status_code=status.HTTP_201_CREATED, dependencies=[gestionar_ventas_requerido]
)
def crear_promocion(datos: PromocionCrear, db: Session = Depends(get_db)) -> PromocionRespuesta:
    return cu_gestionar_promociones.crear(db, datos)


@promociones_router.put("/{promocion_id}", response_model=PromocionRespuesta, dependencies=[gestionar_ventas_requerido])
def actualizar_promocion(
    promocion_id: int, datos: PromocionActualizar, db: Session = Depends(get_db)
) -> PromocionRespuesta:
    return cu_gestionar_promociones.actualizar(db, promocion_id, datos)


@promociones_router.delete("/{promocion_id}", response_model=PromocionRespuesta, dependencies=[gestionar_ventas_requerido])
def desactivar_promocion(promocion_id: int, db: Session = Depends(get_db)) -> PromocionRespuesta:
    return cu_gestionar_promociones.desactivar(db, promocion_id)


# ---- /api/v1/metodos-pago/paypal ------------------------------------------------------
# PayPal guardado del cliente (CU-18): se autoriza UNA vez, con conexión, y el servidor guarda solo el token de PayPal.

metodos_pago_router = APIRouter(
    prefix="/api/v1/metodos-pago", tags=["métodos de pago"], dependencies=[plan_gestion_ventas, digital_requerido]
)


@metodos_pago_router.get("/paypal", response_model=MetodoPagoPayPalRespuesta)
def consultar_paypal_guardado(
    usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> MetodoPagoPayPalRespuesta:
    return cu_metodo_pago_guardado.consultar(db, usuario.id)


@metodos_pago_router.post(
    "/paypal/iniciar", response_model=MetodoPagoPayPalIniciarRespuesta, status_code=status.HTTP_201_CREATED
)
def iniciar_paypal_guardado(
    datos: MetodoPagoPayPalIniciar, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> MetodoPagoPayPalIniciarRespuesta:
    return cu_metodo_pago_guardado.iniciar(db, usuario.id, datos)


@metodos_pago_router.post("/paypal/confirmar", response_model=MetodoPagoPayPalRespuesta)
def confirmar_paypal_guardado(
    datos: MetodoPagoPayPalConfirmar,
    usuario=Depends(get_current_user),
    db: Session = Depends(get_db),
    contexto: ContextoAuditoria = Depends(obtener_contexto_auditoria),
) -> MetodoPagoPayPalRespuesta:
    return cu_metodo_pago_guardado.confirmar(db, usuario.id, datos, contexto)


@metodos_pago_router.delete("/paypal", status_code=status.HTTP_204_NO_CONTENT)
def quitar_paypal_guardado(
    usuario=Depends(get_current_user),
    db: Session = Depends(get_db),
    contexto: ContextoAuditoria = Depends(obtener_contexto_auditoria),
) -> None:
    cu_metodo_pago_guardado.quitar(db, usuario.id, contexto)


# ---- /api/v1/pedidos-diferidos -------------------------------------------------------
# Pedido que el cliente armó SIN conexión; se envía al reconectar y el servidor lo cobra con su PayPal guardado.

pedidos_diferidos_router = APIRouter(
    prefix="/api/v1/pedidos-diferidos",
    tags=["pedidos sin conexión"],
    dependencies=[plan_gestion_ventas, digital_requerido],
)


@pedidos_diferidos_router.post("", response_model=PedidoDiferidoRespuesta)
def enviar_pedido_diferido(
    datos: PedidoDiferidoCrear,
    segundo_plano: BackgroundTasks,
    usuario=Depends(get_current_user),
    db: Session = Depends(get_db),
    contexto: ContextoAuditoria = Depends(obtener_contexto_auditoria),
) -> PedidoDiferidoRespuesta:
    # SIEMPRE 200 cuando el servidor llegó a una decisión final (cobrado o rechazado); el correo sale después de responder.
    return cu_pedido_diferido.ejecutar(db, usuario.id, datos, contexto, segundo_plano.add_task)


_routers_ventas = [
    carrito_router,
    ventas_router,
    devoluciones_router,
    solicitudes_cambio_router,
    metodos_pago_router,
    pedidos_diferidos_router,
    promociones_router,
]


# ---- Pagos ----


gestionar_pagos_requerido = Depends(require_permission(PERMISO_PAGOS))

cu_pagar_pasarela = PagarPasarelaDigital()
cu_procesar_caja = ProcesarPagoCaja()
cu_confirmar_rechazar = ConfirmarRechazarTransaccion()


def _pago_respuesta(db: Session, pago) -> PagoRespuesta:
    return construir_pago_respuesta(db, pago)


# La compuerta va POR RUTA y no en el router: la pantalla QR, su confirmación y
# el webhook no tienen sesión de usuario (el dinero ya se movió) y no pueden
# exigir get_current_user.
pagos_router = APIRouter(prefix="/api/v1/pagos", tags=["pagos"])


@pagos_router.post(
    "/iniciar",
    response_model=PagoIniciarRespuesta,
    status_code=status.HTTP_201_CREATED,
    dependencies=[plan_gestion_ventas],
)
def iniciar_pago(
    datos: PagoIniciarRequest, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> PagoIniciarRespuesta:
    pago, url = cu_pagar_pasarela.iniciar(db, usuario.id, datos)
    return PagoIniciarRespuesta(pago=_pago_respuesta(db, pago), url_redireccion=url)


@pagos_router.post(
    "/caja",
    response_model=PagoCajaRespuesta,
    status_code=status.HTTP_201_CREATED,
    dependencies=[plan_gestion_ventas, gestionar_pagos_requerido],
)
def pagar_en_caja(
    datos: PagoCajaRequest, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> PagoCajaRespuesta:
    pago, cambio = cu_procesar_caja.ejecutar(db, usuario.id, datos)
    return PagoCajaRespuesta(pago=_pago_respuesta(db, pago), cambio=cambio)


@pagos_router.get("/{pago_id}/estado", response_model=PagoRespuesta, dependencies=[plan_gestion_ventas])
def obtener_estado(pago_id: int, usuario=Depends(get_current_user), db: Session = Depends(get_db)) -> PagoRespuesta:
    pago = cu_confirmar_rechazar.obtener_estado(db, usuario.id, pago_id)
    return _pago_respuesta(db, pago)


@pagos_router.post("/venta/{venta_id}/cancelar", dependencies=[plan_gestion_ventas])
def cancelar_compra(venta_id: int, usuario=Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    cu_pagar_pasarela.cancelar(db, usuario.id, venta_id)
    return {"venta_id": venta_id, "estado": "anulada"}


@pagos_router.post(
    "/{pago_id}/anular", response_model=PagoRespuesta, dependencies=[plan_gestion_ventas, gestionar_pagos_requerido]
)
def anular_pago(
    pago_id: int,
    usuario=Depends(get_current_user),
    db: Session = Depends(get_db),
    contexto: ContextoAuditoria = Depends(obtener_contexto_auditoria),
) -> PagoRespuesta:
    pago = cu_confirmar_rechazar.anular(db, usuario.id, pago_id, contexto)
    return _pago_respuesta(db, pago)


# Pantalla pública de la pasarela simulada "qr_online" (ver
# comercial/pasarela.py::QrOnlineGateway). Sin autenticación JWT: la abre un
# WebView/navegador que no tiene por qué estar logueado en la app -- el
# id_transaccion (128 bits) es el único requisito, mismo modelo de
# confianza que un link de pago.
@pagos_router.get("/qr/{id_transaccion}", response_class=HTMLResponse)
def pantalla_qr(id_transaccion: str, db: Session = Depends(get_db)) -> HTMLResponse:
    html = cu_confirmar_rechazar.renderizar_pantalla_qr(db, id_transaccion)
    return HTMLResponse(content=html)


@pagos_router.post("/qr/{id_transaccion}/confirmar", response_model=PagoRespuesta)
def confirmar_qr(id_transaccion: str, db: Session = Depends(get_db)) -> PagoRespuesta:
    pago = cu_confirmar_rechazar.confirmar_pago_qr(db, id_transaccion)
    return _pago_respuesta(db, pago)


# Sin autenticación JWT: lo llama el servidor de la pasarela, no una
# persona logueada. La seguridad acá es la verificación de firma HMAC
# (CU-18.procesar_webhook -> pasarela.verificar_firma), no un permiso.
@pagos_router.post("/webhook/{pasarela}", response_model=PagoRespuesta)
async def recibir_webhook(
    pasarela: str,
    request: Request,
    db: Session = Depends(get_db),
    x_signature: str | None = Header(default=None),
) -> PagoRespuesta:
    payload_crudo = await request.body()
    pago = cu_confirmar_rechazar.procesar_webhook(db, pasarela, payload_crudo, x_signature)
    return _pago_respuesta(db, pago)


# Protegida por token de servicio, igual que /tareas/expirar-reservas. Además
# la corre sola la tarea periódica de app/main.py (lifespan).
# expirar_ventas_pendientes no es un caso de uso del catálogo (no tiene
# actor humano): vive en comercial/politicas.py.
tareas_pagos_router = APIRouter(prefix="/api/v1/tareas", tags=["tareas"], dependencies=[Depends(require_service_token)])


@tareas_pagos_router.post("/expirar-ventas-pendientes")
def expirar_ventas_pendientes_endpoint(db: Session = Depends(get_db)) -> dict:
    return expirar_ventas_de_todas_las_empresas(db)


_routers_pagos = [pagos_router, tareas_pagos_router]


# ---- Entregas ----


gestionar_entregas_requerido = Depends(require_permission(PERMISO_ENTREGAS))

cu_gestionar_zonas = GestionarZonasTarifas()
cu_solicitar_envio = SolicitarEnvioDomicilio()
cu_actualizar_estado = ActualizarEstadoEnvio()


# ---- /api/v1/zonas-envio ----------------------------------------------------
# GET es público (el checkout necesita listarlas para elegir); escribir es
# solo de administración/logística.

zonas_router = APIRouter(prefix="/api/v1/zonas-envio", tags=["zonas-envio"])


@zonas_router.get("", response_model=list[ZonaEnvioRespuesta])
def listar_zonas(
    db: Session = Depends(get_db), paginacion: ParametrosPaginacion = Depends(parametros_paginacion)
) -> list[ZonaEnvioRespuesta]:
    return cu_gestionar_zonas.listar(db, paginacion)


@zonas_router.get("/{zona_id}", response_model=ZonaEnvioRespuesta)
def obtener_zona(zona_id: int, db: Session = Depends(get_db)) -> ZonaEnvioRespuesta:
    return cu_gestionar_zonas.obtener(db, zona_id)


@zonas_router.post(
    "",
    response_model=ZonaEnvioRespuesta,
    status_code=status.HTTP_201_CREATED,
    dependencies=[plan_gestion_ventas, gestionar_entregas_requerido],
)
def crear_zona(datos: ZonaEnvioCrear, db: Session = Depends(get_db)) -> ZonaEnvioRespuesta:
    return cu_gestionar_zonas.crear(db, datos)


@zonas_router.put(
    "/{zona_id}", response_model=ZonaEnvioRespuesta, dependencies=[plan_gestion_ventas, gestionar_entregas_requerido]
)
def actualizar_zona(zona_id: int, datos: ZonaEnvioActualizar, db: Session = Depends(get_db)) -> ZonaEnvioRespuesta:
    return cu_gestionar_zonas.actualizar(db, zona_id, datos)


@zonas_router.delete(
    "/{zona_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[plan_gestion_ventas, gestionar_entregas_requerido]
)
def desactivar_zona(zona_id: int, db: Session = Depends(get_db)) -> None:
    cu_gestionar_zonas.desactivar(db, zona_id)


# ---- /api/v1/clientes/direcciones ---------------------------------------------
# Recurso propio del cliente logueado: no se listan/editan direcciones de
# otro cliente por id, ver SolicitarEnvioDomicilio._validar_acceso_direccion.

direcciones_router = APIRouter(
    prefix="/api/v1/clientes/direcciones", tags=["direcciones"], dependencies=[digital_requerido]
)


@direcciones_router.get("", response_model=list[DireccionClienteRespuesta])
def listar_mis_direcciones(
    usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> list[DireccionClienteRespuesta]:
    return cu_solicitar_envio.listar_mis_direcciones(db, usuario.id)


@direcciones_router.post("", response_model=DireccionClienteRespuesta, status_code=status.HTTP_201_CREATED)
def crear_mi_direccion(
    datos: DireccionClienteCrear, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> DireccionClienteRespuesta:
    return cu_solicitar_envio.crear_mi_direccion(db, usuario.id, datos)


@direcciones_router.put("/{direccion_id}", response_model=DireccionClienteRespuesta)
def actualizar_mi_direccion(
    direccion_id: int,
    datos: DireccionClienteActualizar,
    usuario=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DireccionClienteRespuesta:
    return cu_solicitar_envio.actualizar_mi_direccion(db, usuario.id, direccion_id, datos)


@direcciones_router.delete("/{direccion_id}", status_code=status.HTTP_204_NO_CONTENT)
def desactivar_mi_direccion(
    direccion_id: int, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> None:
    cu_solicitar_envio.desactivar_mi_direccion(db, usuario.id, direccion_id)


# ---- /api/v1/envios ----------------------------------------------------------

# La compuerta va POR RUTA: `cotizar` acepta peticiones sin usuario (la misma
# cotización es pública bajo /public/{codigo}/envios/cotizar) y la compuerta
# exige sesión.
envios_router = APIRouter(prefix="/api/v1/envios", tags=["envios"])


@envios_router.post("/cotizar", response_model=CotizarEnvioRespuesta)
def cotizar_envio(datos: CotizarEnvioRequest, db: Session = Depends(get_db)) -> CotizarEnvioRespuesta:
    return cu_solicitar_envio.cotizar(db, datos)


@envios_router.post(
    "", response_model=EnvioRespuesta, status_code=status.HTTP_201_CREATED, dependencies=[plan_gestion_ventas]
)
def crear_envio(
    datos: EnvioCrear, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> EnvioRespuesta:
    return cu_solicitar_envio.crear_envio(db, usuario.id, datos)


@envios_router.get(
    "", response_model=list[EnvioRespuesta], dependencies=[plan_gestion_ventas, gestionar_entregas_requerido]
)
def listar_envios(
    estado: EstadoEnvio | None = None,
    sucursal_id: int | None = None,
    usuario=Depends(get_current_user),
    db: Session = Depends(get_db),
    paginacion: ParametrosPaginacion = Depends(parametros_paginacion),
) -> list[EnvioRespuesta]:
    return cu_actualizar_estado.listar(db, usuario.id, paginacion, estado, sucursal_id)


@envios_router.get("/venta/{venta_id}", response_model=EnvioRespuesta, dependencies=[plan_gestion_ventas])
def obtener_envio_de_venta(
    venta_id: int, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> EnvioRespuesta:
    return cu_actualizar_estado.obtener_por_venta(db, usuario.id, venta_id)


@envios_router.get("/{envio_id}", response_model=EnvioRespuesta, dependencies=[plan_gestion_ventas])
def obtener_envio(envio_id: int, usuario=Depends(get_current_user), db: Session = Depends(get_db)) -> EnvioRespuesta:
    return cu_actualizar_estado.obtener(db, usuario.id, envio_id)


@envios_router.put(
    "/{envio_id}/estado", response_model=EnvioRespuesta, dependencies=[plan_gestion_ventas, gestionar_entregas_requerido]
)
def actualizar_estado_envio(
    envio_id: int, datos: EnvioEstadoActualizar, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> EnvioRespuesta:
    return cu_actualizar_estado.actualizar_estado(db, usuario.id, envio_id, datos)


_routers_entregas = [zonas_router, direcciones_router, envios_router]


# ---- /api/v1/public/{codigo} (tienda pública por empresa) --------------------------
# Los MISMOS handlers públicos de zonas de envío y cotización, bajo el código de
# la tienda (D02, D10). La empresa la fija `contexto_empresa` (core/tenant.py)
# desde el código de la ruta; `_codigo_tienda` solo documenta el parámetro en
# OpenAPI. No se copian handlers.


def _codigo_tienda(codigo: str) -> str:
    return codigo


publico_tienda_router = APIRouter(
    prefix="/api/v1/public/{codigo}", tags=["tienda-publica"], dependencies=[Depends(_codigo_tienda)]
)

for _ruta, _metodo, _handler, _modelo in (
    ("/zonas-envio", "GET", listar_zonas, list[ZonaEnvioRespuesta]),
    ("/zonas-envio/{zona_id}", "GET", obtener_zona, ZonaEnvioRespuesta),
    ("/envios/cotizar", "POST", cotizar_envio, CotizarEnvioRespuesta),
):
    publico_tienda_router.add_api_route(_ruta, _handler, methods=[_metodo], response_model=_modelo)


routers = _routers_reservas + _routers_ventas + _routers_pagos + _routers_entregas + [publico_tienda_router]
