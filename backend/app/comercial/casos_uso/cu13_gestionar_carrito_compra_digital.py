"""CU-13 — Gestionar carrito y compra digital

Absorbe los antiguos CU-23 (Gestionar carrito) y CU-24 (Realizar compra
digital).

Actor: Cliente.
Precondición: el cliente tiene sesión iniciada; la variante a agregar
existe; para comprar, el carrito no está vacío.
Postcondición: el carrito queda guardado con sus líneas y el total
calculado (con las promociones vigentes aplicadas); al comprar se crea la
venta en estado pendiente_pago, y el pago (CU-18) y, si hay envío, la
cotización de entrega (CU-19) se disparan después.

Caso de uso COMPUESTO: agrupa gestionar el carrito (incluye aplicar las
promociones vigentes al total) y realizar la compra digital, un envoltorio
fino sobre comercial.politicas.registrar_venta que no reimplementa la lógica
común con CU-14.

También la clase de control `RealizarPedidoDiferido`: el pedido que el cliente
armó SIN conexión y que el servidor cobra al reconectar con el PayPal que el
cliente guardó antes (`GestionarMetodoPagoGuardado`, CU-18). En UNA llamada
revalida stock, precios y el tope que el cliente aceptó, crea la venta digital,
cobra con PayPal y la confirma; el resultado FINAL queda guardado por
(empresa, operación) para que reenviar no cobre dos veces."""

import datetime as dt
import logging
from collections.abc import Callable
from decimal import Decimal

from sqlalchemy.orm import Session

from app.catalogo import politicas as catalogo_politicas
from app.catalogo.casos_uso.cu09_gestionar_inventario import ConsultarDisponibilidadSucursal
from app.comercial.models import Carrito, CarritoDetalle, MetodoPagoGuardado, PedidoDiferido, Venta
from app.comercial.pasarela import monto_en_usd
from app.comercial.politicas import (
    MOTIVO_PAGO_RECHAZADO,
    MOTIVO_PEDIDO_INVALIDO,
    MOTIVO_PEDIDO_VENCIDO,
    MOTIVO_SIN_METODO_PAGO,
    MOTIVO_STOCK_INSUFICIENTE,
    MOTIVO_TOTAL_SUPERA_MAXIMO,
    MOTIVO_VARIANTE_INACTIVA,
    PagoIncierto,
    RechazoPedido,
    calcular_linea,
    construir_correo_pedido_diferido,
    despachar_correo,
    destinatario_de_usuario,
    obtener_venta,
    paypal_rechazo_definitivo,
    redondear,
    registrar_cobro_pasarela_aprobado,
    registrar_venta,
    request_id_de_pedido,
)
from app.comercial.repository import CarritoRepository, MetodoPagoGuardadoRepository, PedidoDiferidoRepository
from app.comercial.schemas import (
    CarritoDetalleActualizar,
    CarritoDetalleCrear,
    CarritoDetalleRespuesta,
    CarritoRespuesta,
    CarritoResumenLinea,
    CarritoResumenRespuesta,
    PedidoDiferidoCrear,
    PedidoDiferidoRespuesta,
    VentaDigitalCrear,
)
from app.core import paypal
from app.core.auditoria import (
    ACCION_COBRAR,
    ACCION_RECHAZAR,
    ENTIDAD_PEDIDO_DIFERIDO,
    ContextoAuditoria,
)
from app.core.config import get_settings
from app.core.correo import MensajeCorreo, envio_configurado
from app.core.tiempo import hoy_utc
from app.core.exceptions import (
    ConflictoError,
    DemasiadosIntentosError,
    DomainError,
    ErrorFuncional,
    NoEncontradoError,
    StockInsuficienteError,
)
from app.core.rate_limit import limitador_pedido_diferido
from app.plataforma import politicas as plataforma_politicas
from app.plataforma.politicas import obtener_perfil_cliente

logger = logging.getLogger(__name__)


# ---- Gestionar carrito (antiguo CU-23) ----

class GestionarCarrito:
    def __init__(self) -> None:
        self._carritos = CarritoRepository()
        self._disponibilidad = ConsultarDisponibilidadSucursal()

    def _respuesta(self, db: Session, carrito: Carrito) -> CarritoRespuesta:
        """Una línea cuya variante se dio de baja después de agregarla se
        sigue devolviendo (disponible=False) para que el cliente la vea y la
        quite, pero no suma al subtotal. Antes obtener_variante lanzaba 404
        y el cliente se quedaba sin poder ver ni vaciar su carrito."""
        detalle_resp = []
        subtotal = Decimal("0")
        for linea in carrito.detalle:
            variante = catalogo_politicas.buscar_variante(db, linea.variante_id)
            disponible = variante is not None and variante.activo
            precio_unitario = catalogo_politicas.obtener_precio_efectivo(variante) if variante else Decimal("0")
            subtotal_linea = redondear(precio_unitario * linea.cantidad)
            detalle_resp.append(
                CarritoDetalleRespuesta(
                    id=linea.id,
                    variante_id=linea.variante_id,
                    cantidad=linea.cantidad,
                    precio_unitario=precio_unitario,
                    subtotal=subtotal_linea,
                    disponible=disponible,
                )
            )
            if disponible:
                subtotal += subtotal_linea

        return CarritoRespuesta(
            id=carrito.id,
            cliente_id=carrito.cliente_id,
            sucursal_id=carrito.sucursal_id,
            actualizado_en=carrito.actualizado_en,
            detalle=detalle_resp,
            subtotal=redondear(subtotal),
        )

    def _validar_stock(self, db: Session, variante_id: int, cantidad: int) -> None:
        """El carrito todavía no elige sucursal: se valida contra el
        disponible total de la variante. La sucursal concreta se vuelve a
        validar al registrar la venta (comercial.politicas.registrar_venta)."""
        disponible = sum(s.cantidad_disponible for s in self._disponibilidad.ejecutar(db, variante_id))
        if cantidad > disponible:
            if disponible <= 0:
                raise ConflictoError("Esta prenda está agotada")
            raise ConflictoError(f"Solo quedan {disponible} unidades disponibles")

    def obtener_mi_carrito(self, db: Session, usuario_id: int) -> CarritoRespuesta:
        cliente = obtener_perfil_cliente(db, usuario_id)
        carrito = self._carritos.obtener_o_crear(db, cliente.id)
        db.commit()  # persiste el carrito si obtener_o_crear tuvo que crearlo
        return self._respuesta(db, carrito)

    def agregar(self, db: Session, usuario_id: int, datos: CarritoDetalleCrear) -> CarritoRespuesta:
        cliente = obtener_perfil_cliente(db, usuario_id)
        catalogo_politicas.obtener_variante(db, datos.variante_id)  # 404 si no existe
        carrito = self._carritos.obtener_o_crear(db, cliente.id)

        linea = self._carritos.obtener_linea(db, carrito.id, datos.variante_id)
        self._validar_stock(db, datos.variante_id, datos.cantidad + (linea.cantidad if linea else 0))
        if linea is None:
            db.add(CarritoDetalle(carrito_id=carrito.id, variante_id=datos.variante_id, cantidad=datos.cantidad))
        else:
            linea.cantidad += datos.cantidad

        db.commit()
        db.refresh(carrito)
        return self._respuesta(db, carrito)

    def actualizar_linea(
        self, db: Session, usuario_id: int, variante_id: int, datos: CarritoDetalleActualizar
    ) -> CarritoRespuesta:
        cliente = obtener_perfil_cliente(db, usuario_id)
        carrito = self._carritos.obtener_o_crear(db, cliente.id)
        linea = self._carritos.obtener_linea(db, carrito.id, variante_id)
        if linea is None:
            raise NoEncontradoError("Esa variante no está en el carrito")

        if datos.cantidad > linea.cantidad:  # bajar la cantidad nunca se bloquea
            variante = catalogo_politicas.buscar_variante(db, variante_id)
            if variante is None or not variante.activo:
                raise ConflictoError("Esta prenda ya no está disponible")
            self._validar_stock(db, variante_id, datos.cantidad)
        linea.cantidad = datos.cantidad
        db.commit()
        db.refresh(carrito)
        return self._respuesta(db, carrito)

    def quitar(self, db: Session, usuario_id: int, variante_id: int) -> CarritoRespuesta:
        cliente = obtener_perfil_cliente(db, usuario_id)
        carrito = self._carritos.obtener_o_crear(db, cliente.id)
        linea = self._carritos.obtener_linea(db, carrito.id, variante_id)
        if linea is None:
            raise NoEncontradoError("Esa variante no está en el carrito")

        self._carritos.quitar_linea(db, linea)
        db.commit()
        db.refresh(carrito)
        return self._respuesta(db, carrito)

    def previsualizar(self, db: Session, usuario_id: int) -> CarritoResumenRespuesta:
        """POST /carrito/aplicar-promocion: no hay código de cupón que
        canjear (`promocion` no tiene esa columna) -- esto recalcula el
        carrito con las promociones vigentes ya aplicadas solas, según
        `promocion_alcance`."""
        cliente = obtener_perfil_cliente(db, usuario_id)
        carrito = self._carritos.obtener_o_crear(db, cliente.id)
        db.commit()
        hoy = hoy_utc()

        lineas: list[CarritoResumenLinea] = []
        subtotal = Decimal("0")
        descuento = Decimal("0")
        for linea in carrito.detalle:
            variante = catalogo_politicas.buscar_variante(db, linea.variante_id)
            if variante is None or not variante.activo:
                continue  # dada de baja: no se puede comprar, no entra en el total
            precio_unitario, descuento_unitario, subtotal_linea = calcular_linea(db, variante, linea.cantidad, hoy)
            lineas.append(
                CarritoResumenLinea(
                    variante_id=linea.variante_id,
                    cantidad=linea.cantidad,
                    precio_unitario=precio_unitario,
                    descuento_unitario=descuento_unitario,
                    subtotal=subtotal_linea,
                )
            )
            subtotal += precio_unitario * linea.cantidad
            descuento += descuento_unitario * linea.cantidad

        subtotal = redondear(subtotal)
        descuento = redondear(descuento)
        return CarritoResumenRespuesta(lineas=lineas, subtotal=subtotal, descuento=descuento, total=subtotal - descuento)


# ---- Realizar compra digital (antiguo CU-24) ----

class RealizarCompraDigital:
    def __init__(self) -> None:
        self._carritos = CarritoRepository()

    def ejecutar(self, db: Session, usuario_id: int, datos: VentaDigitalCrear) -> Venta:
        cliente = obtener_perfil_cliente(db, usuario_id)
        carrito = self._carritos.obtener_por_cliente(db, cliente.id)
        if carrito is None or not carrito.detalle:
            raise DomainError("El carrito está vacío")

        # Una prenda que se dio de baja después de agregarla no se puede
        # comprar: se le pide al cliente que la quite (el carrito se la
        # muestra con disponible=False) en vez de fallar con un 404.
        for linea in carrito.detalle:
            variante = catalogo_politicas.buscar_variante(db, linea.variante_id)
            if variante is None or not variante.activo:
                raise ConflictoError("Hay prendas en tu carrito que ya no están disponibles: quitalas para continuar")

        lineas = [(linea.variante_id, linea.cantidad) for linea in carrito.detalle]

        # Sin costo de envío es retiro en sucursal (el envío a domicilio
        # siempre cobra la tarifa de la zona, CU-19): no se puede retirar
        # en un depósito.
        if datos.costo_envio == 0 and not plataforma_politicas.atiende_al_publico(db, datos.sucursal_id):
            raise DomainError("Esa sucursal no atiende al público: elegí otra para retirar tu pedido")

        return registrar_venta(
            db,
            canal="digital",
            sucursal_id=datos.sucursal_id,
            lineas=lineas,
            cliente_id=cliente.id,
            cajero_id=None,
            reserva_id=None,
            costo_envio=datos.costo_envio,
            usuario_id=usuario_id,
            carrito_a_vaciar=carrito,
        )


# ---- Realizar pedido sin conexión ----

# `programar_envio(funcion, mensaje)` deja un correo para DESPUÉS de responder (el router pasa `BackgroundTasks.add_task`).
ProgramarEnvio = Callable[[Callable[[MensajeCorreo], object], MensajeCorreo], object]


def _no_disponible() -> ErrorFuncional:
    return ErrorFuncional(
        "paypal_no_disponible",
        "No pudimos completar el cobro ahora. Reintenta en unos minutos con el mismo pedido: no se cobrará dos veces.",
        503,
    )


class RealizarPedidoDiferido:
    """Procesa UN pedido que el cliente armó sin conexión, cuando vuelve la conexión.

    Reglas que importan:
    - **Idempotencia.** `operacion_id` (UUID del cliente) con UNIQUE (empresa, operación). Reenviarla devuelve lo guardado
      (`duplicada=true`) sin volver a cobrar. Un reenvío no cuenta para el límite de pedidos por cuenta.
    - **Decisión final o nada.** Cobrado o rechazado se guardan con su motivo (HTTP 200). Un fallo temporal (PayPal o la
      red no responden, resultado incierto) NO guarda nada y responde 503: todo, incluidos la venta y el stock apartado,
      va en UNA transacción que se revierte. El cobro usa `PayPal-Request-Id` derivado de (empresa, operación) y el mismo
      cuerpo (referencia = la operación): si PayPal sí cobró y la respuesta se perdió, el reintento recibe la orden
      original y NO se cobra dos veces; la venta se arma de nuevo y se confirma con ese cobro.
    - **Stock.** La venta nace `pendiente_pago` con el stock RESERVADO (`registrar_venta`), PayPal cobra y recién entonces
      `confirmar_venta` lo descuenta. Si PayPal rechaza, o el total real supera `total_maximo`, la venta no queda.
    - **Ids.** Una sucursal o prenda que no es de la empresa responde 404, igual que una inexistente, antes de guardar nada.
    - **Avisos.** Notificación dentro del sistema (misma transacción) y correo por Brevo (después de responder; sin Brevo
      o si falla, el pedido no se ve afectado)."""

    def __init__(self) -> None:
        self._pedidos = PedidoDiferidoRepository()
        self._metodos = MetodoPagoGuardadoRepository()

    def ejecutar(
        self,
        db: Session,
        usuario_id: int,
        datos: PedidoDiferidoCrear,
        contexto: ContextoAuditoria | None = None,
        programar_envio: ProgramarEnvio | None = None,
    ) -> PedidoDiferidoRespuesta:
        cliente = obtener_perfil_cliente(db, usuario_id)
        previa = self._pedidos.obtener_por_operacion(db, datos.operacion_id)
        if previa is not None:
            return self._duplicada(db, usuario_id, previa)

        # Todo id del cliente se resuelve ANTES de guardar nada: lo ajeno o inexistente es un 404 idéntico.
        sucursal = plataforma_politicas.obtener_sucursal(db, datos.sucursal_id)
        variantes = {}
        for linea in datos.lineas:
            variante = catalogo_politicas.buscar_variante(db, linea.variante_id)
            if variante is None:
                raise NoEncontradoError("Prenda no encontrada")
            variantes[linea.variante_id] = variante

        clave = str(usuario_id)
        espera = limitador_pedido_diferido.bloqueado(clave)
        if espera is not None:
            raise DemasiadosIntentosError(espera, "Enviaste muchos pedidos. Intenta de nuevo más tarde.")
        limitador_pedido_diferido.registrar_fallo(clave)  # cuenta cada pedido nuevo (no es un "fallo")

        fila = self._pedidos.reservar_clave(
            db, operacion_id=datos.operacion_id, usuario_id=usuario_id, sucursal_id=sucursal.id, estado="en_proceso"
        )
        if fila is None:  # otro envío de la misma operación llegó primero y ya confirmó
            return self._duplicada(db, usuario_id, self._pedidos.obtener_por_operacion(db, datos.operacion_id))

        venta = None
        total_usd = None
        rechazo: RechazoPedido | None = None
        try:
            self._validar(db, usuario_id, datos, sucursal, variantes)
            with db.begin_nested():  # si algo falla aquí dentro, ni la venta ni el stock apartado quedan
                venta, total_usd = self._vender_y_cobrar(db, usuario_id, cliente, datos, sucursal)
        except RechazoPedido as decision:
            rechazo = decision
        except StockInsuficienteError as exc:
            rechazo = RechazoPedido(MOTIVO_STOCK_INSUFICIENTE, self._mensaje_de_stock(db, exc))
        except PagoIncierto as exc:
            db.rollback()
            logger.warning("pedido_diferido_incierto op=%s causa=%s", str(datos.operacion_id)[:8], exc)
            raise _no_disponible() from exc
        except ErrorFuncional:
            db.rollback()
            raise
        except DomainError as exc:
            rechazo = RechazoPedido(MOTIVO_PEDIDO_INVALIDO, exc.mensaje)
        except Exception:
            db.rollback()
            raise

        try:
            if rechazo is None:
                self._cerrar_cobrado(db, usuario_id, fila, venta, total_usd, sucursal, datos, contexto)
            else:
                self._cerrar_rechazado(db, usuario_id, fila, rechazo, datos, contexto)
            db.commit()
        except Exception as exc:
            # Si PayPal ya había cobrado, el reintento con la MISMA operación recibe el cobro original (idempotencia).
            db.rollback()
            logger.exception("pedido_diferido_no_guardado op=%s cobrado=%s", str(datos.operacion_id)[:8], rechazo is None)
            raise _no_disponible() from exc

        db.refresh(fila)
        codigo_venta = venta.codigo if venta is not None else None
        self._avisar_por_correo(db, usuario_id, sucursal, fila, codigo_venta, programar_envio)
        return self._respuesta(fila, codigo_venta, duplicada=False)

    # -- validaciones previas (sin escribir nada) -----------------------------------------------

    def _validar(self, db: Session, usuario_id: int, datos: PedidoDiferidoCrear, sucursal, variantes: dict) -> None:
        ajustes = get_settings()
        self._validar_fecha(datos, ajustes)
        if len(datos.lineas) > ajustes.pedido_diferido_max_lineas:
            raise RechazoPedido(
                MOTIVO_PEDIDO_INVALIDO,
                f"Tu pedido tiene demasiadas prendas distintas (máximo {ajustes.pedido_diferido_max_lineas}).",
            )
        if any(linea.cantidad > ajustes.pedido_diferido_max_unidades_por_linea for linea in datos.lineas):
            raise RechazoPedido(
                MOTIVO_PEDIDO_INVALIDO,
                f"Puedes pedir hasta {ajustes.pedido_diferido_max_unidades_por_linea} unidades de cada prenda.",
            )
        if sum(linea.cantidad for linea in datos.lineas) > ajustes.pedido_diferido_max_unidades:
            raise RechazoPedido(
                MOTIVO_PEDIDO_INVALIDO,
                f"Tu pedido supera las {ajustes.pedido_diferido_max_unidades} unidades permitidas.",
            )
        if datos.costo_envio > ajustes.pedido_diferido_max_costo_envio:
            raise RechazoPedido(MOTIVO_PEDIDO_INVALIDO, "El costo de envío de tu pedido no es válido.")
        # Igual que la compra digital: sin costo de envío es retiro en sucursal, y un depósito no atiende al público.
        if datos.costo_envio == 0 and not plataforma_politicas.atiende_al_publico(db, sucursal.id):
            raise RechazoPedido(
                MOTIVO_PEDIDO_INVALIDO, "Esa sucursal no atiende al público: elige otra para retirar tu pedido."
            )
        for linea in datos.lineas:
            variante = variantes[linea.variante_id]
            if not variante.activo or not variante.producto.activo:
                raise RechazoPedido(
                    MOTIVO_VARIANTE_INACTIVA,
                    f"{catalogo_politicas.describir_variante(db, variante)} ya no está disponible. Tu pedido no se cobró.",
                )
        metodo = self._metodos.obtener_activo(db, usuario_id)
        if metodo is None or not metodo.payment_token_id:
            raise RechazoPedido(
                MOTIVO_SIN_METODO_PAGO,
                "No tienes un PayPal guardado. Guárdalo con conexión y vuelve a hacer tu pedido. No se cobró nada.",
            )

    @staticmethod
    def _validar_fecha(datos: PedidoDiferidoCrear, ajustes) -> None:
        """`fecha_pedido` (cuándo lo armó el cliente) no decide precios, pero un pedido de hace más de
        `pedido_diferido_max_dias` días vence, y una fecha futura más allá de la tolerancia (reloj mal puesto) es
        inválida. Sin fecha no se comprueba nada. Una fecha sin zona se toma como UTC."""
        if datos.fecha_pedido is None:
            return
        fecha = datos.fecha_pedido
        if fecha.tzinfo is None:
            fecha = fecha.replace(tzinfo=dt.timezone.utc)
        ahora = dt.datetime.now(dt.timezone.utc)
        if fecha > ahora + dt.timedelta(hours=ajustes.pedido_diferido_tolerancia_futuro_horas):
            raise RechazoPedido(
                MOTIVO_PEDIDO_INVALIDO, "La fecha de tu pedido no es válida. Revisa la fecha y la hora de tu dispositivo."
            )
        if fecha < ahora - dt.timedelta(days=ajustes.pedido_diferido_max_dias):
            raise RechazoPedido(
                MOTIVO_PEDIDO_VENCIDO,
                f"Tu pedido venció: pasaron más de {ajustes.pedido_diferido_max_dias} días sin conexión. No se cobró nada.",
            )

    # -- la venta y el cobro, dentro de un SAVEPOINT -------------------------------------------

    def _vender_y_cobrar(self, db: Session, usuario_id: int, cliente, datos: PedidoDiferidoCrear, sucursal):
        metodo: MetodoPagoGuardado = self._metodos.obtener_activo(db, usuario_id)
        venta = registrar_venta(
            db,
            canal="digital",
            sucursal_id=sucursal.id,
            lineas=[(linea.variante_id, linea.cantidad) for linea in datos.lineas],
            cliente_id=cliente.id,
            cajero_id=None,
            reserva_id=None,
            costo_envio=datos.costo_envio,
            usuario_id=usuario_id,
            commit=False,
        )
        if venta.total > datos.total_maximo:
            raise RechazoPedido(
                MOTIVO_TOTAL_SUPERA_MAXIMO,
                f"El total actual (Bs {venta.total}) supera el máximo que aceptaste (Bs {datos.total_maximo}). "
                "Tu pedido no se cobró.",
            )
        total_usd, tipo_cambio = monto_en_usd(venta.total)

        try:
            orden = paypal.cobrar_con_vault(
                vault_id=metodo.payment_token_id,
                monto=total_usd,
                moneda="USD",
                # Cuerpo FIJO por operación: si el reintento cambiara el cuerpo, PayPal rechazaría la misma clave de
                # idempotencia. Por eso la referencia es la operación y no el código de la venta (que cambia).
                referencia=str(datos.operacion_id),
                descripcion="Pedido hecho sin conexión",
                request_id=request_id_de_pedido(venta.empresa_id, datos.operacion_id),
            )
        except paypal.PayPalError as exc:
            definitivo = paypal_rechazo_definitivo(exc)
            logger.warning(
                "pedido_diferido_paypal_error op=%s estado_http=%s definitivo=%s",
                str(datos.operacion_id)[:8], exc.status_code, definitivo,
            )  # fmt: skip
            if definitivo:
                raise RechazoPedido(MOTIVO_PAGO_RECHAZADO, "PayPal rechazó el cobro. Tu pedido no se cobró.") from exc
            raise PagoIncierto("PayPal no respondió bien") from exc

        if orden.estado != paypal.ESTADO_COMPLETADA:
            raise RechazoPedido(MOTIVO_PAGO_RECHAZADO, "PayPal no autorizó el cobro. Tu pedido no se cobró.")
        if orden.estado_captura not in (None, paypal.ESTADO_COMPLETADA):
            if orden.estado_captura == "PENDING":  # PayPal retiene el cobro para revisarlo: no se sabe todavía
                raise PagoIncierto("la captura quedó pendiente en PayPal")
            raise RechazoPedido(MOTIVO_PAGO_RECHAZADO, "PayPal rechazó el cobro. Tu pedido no se cobró.")
        if orden.monto is not None and (orden.moneda != "USD" or orden.monto != total_usd):
            logger.error("pedido_diferido_monto_no_coincide op=%s", str(datos.operacion_id)[:8])
            raise PagoIncierto("PayPal informó otro monto u otra moneda")

        # El dinero YA se movió: desde aquí cualquier fallo es "incierto" (nada se guarda; el reintento recibe el mismo
        # cobro de PayPal y vuelve a armar la venta), jamás un rechazo.
        try:
            registrar_cobro_pasarela_aprobado(
                db,
                venta,
                pasarela_codigo="paypal",
                id_transaccion=orden.id,
                monto_usd=total_usd,
                tipo_cambio=tipo_cambio,
                origen="pedido_diferido",
                avisar_compra=False,  # el pedido sin conexión ya tiene su propio correo y su notificación
            )
            db.refresh(venta)
        except Exception as exc:
            logger.exception("pedido_diferido_cobrado_sin_confirmar op=%s", str(datos.operacion_id)[:8])
            raise PagoIncierto("el cobro se hizo pero la venta no se pudo confirmar") from exc
        return venta, total_usd

    # -- cierre ---------------------------------------------------------------------------------

    @staticmethod
    def _cerrar_cobrado(
        db: Session,
        usuario_id: int,
        fila: PedidoDiferido,
        venta: Venta,
        total_usd: Decimal,
        sucursal,
        datos: PedidoDiferidoCrear,
        contexto: ContextoAuditoria | None,
    ) -> None:
        mensaje = f"Cobramos tu pedido {venta.codigo} por Bs {venta.total} (sucursal {sucursal.nombre})."
        fila.estado = "cobrado"
        fila.motivo = None
        fila.mensaje = mensaje[:300]
        fila.venta_id = venta.id
        fila.total = venta.total
        fila.total_usd = total_usd
        plataforma_politicas.crear_notificacion(
            db, usuario_id, "Cobramos tu pedido", mensaje[:400], "pedido_diferido", venta.id, commit=False
        )
        plataforma_politicas.registrar_bitacora_de(
            db,
            contexto,
            ENTIDAD_PEDIDO_DIFERIDO,
            fila.id,
            ACCION_COBRAR,
            {"venta_id": venta.id, "lineas": len(datos.lineas), "unidades": sum(x.cantidad for x in datos.lineas)},
        )

    @staticmethod
    def _cerrar_rechazado(
        db: Session,
        usuario_id: int,
        fila: PedidoDiferido,
        rechazo: RechazoPedido,
        datos: PedidoDiferidoCrear,
        contexto: ContextoAuditoria | None,
    ) -> None:
        fila.estado = "rechazado"
        fila.motivo = rechazo.motivo
        fila.mensaje = rechazo.mensaje[:300]
        plataforma_politicas.crear_notificacion(
            db, usuario_id, "No pudimos cobrar tu pedido", rechazo.mensaje[:400], "pedido_diferido", None, commit=False
        )
        plataforma_politicas.registrar_bitacora_de(
            db,
            contexto,
            ENTIDAD_PEDIDO_DIFERIDO,
            fila.id,
            ACCION_RECHAZAR,
            {"motivo": rechazo.motivo, "lineas": len(datos.lineas)},
        )

    # -- respuestas -----------------------------------------------------------------------------

    def _duplicada(self, db: Session, usuario_id: int, fila: PedidoDiferido) -> PedidoDiferidoRespuesta:
        """Ya se había decidido: se devuelve lo guardado (el cuerpo nuevo se ignora). La operación de otra persona se ve
        inexistente."""
        if fila.usuario_id != usuario_id:
            raise NoEncontradoError("Pedido no encontrado")
        if fila.estado == "en_proceso":  # no se confirma jamás en este estado: defensa
            raise _no_disponible()
        codigo = obtener_venta(db, fila.venta_id).codigo if fila.venta_id is not None else None
        return self._respuesta(fila, codigo, duplicada=True)

    @staticmethod
    def _respuesta(fila: PedidoDiferido, codigo_venta: str | None, *, duplicada: bool) -> PedidoDiferidoRespuesta:
        cobrado = fila.estado == "cobrado"
        return PedidoDiferidoRespuesta(
            operacion_id=fila.operacion_id,
            estado=fila.estado,
            motivo=fila.motivo,
            mensaje=fila.mensaje or "",
            venta_id=fila.venta_id if cobrado else None,
            codigo_venta=codigo_venta if cobrado else None,
            total=fila.total if cobrado else None,
            total_usd=fila.total_usd if cobrado else None,
            duplicada=duplicada,
        )

    @staticmethod
    def _mensaje_de_stock(db: Session, error: StockInsuficienteError) -> str:
        variante = catalogo_politicas.buscar_variante(db, error.variante_id) if error.variante_id else None
        prenda = catalogo_politicas.describir_variante(db, variante) if variante is not None else "una prenda"
        return f"No hay stock suficiente de {prenda}. Tu pedido no se cobró."

    @staticmethod
    def _avisar_por_correo(
        db: Session, usuario_id: int, sucursal, fila: PedidoDiferido, codigo_venta: str | None, programar_envio
    ) -> None:
        """Correo de 'cobramos tu pedido' o 'no pudimos cobrarlo'. Nunca lanza: la decisión ya está confirmada."""
        try:
            if not envio_configurado():
                return
            destinatario = destinatario_de_usuario(db, usuario_id)
            if destinatario is None:
                return
            empresa = plataforma_politicas.obtener_empresa_de_la_sesion(db)
            mensaje = construir_correo_pedido_diferido(
                para_email=destinatario[0],
                nombre=destinatario[1],
                nombre_empresa=empresa.nombre,
                sucursal=sucursal.nombre,
                codigo_venta=codigo_venta,
                total=fila.total,
                motivo=fila.motivo,
            )
            despachar_correo(mensaje, programar_envio)
        except Exception:  # noqa: BLE001 - el aviso es un extra: jamás deshace el pedido
            logger.exception("aviso_pedido_diferido_no_armado pedido_id=%s", fila.id)
