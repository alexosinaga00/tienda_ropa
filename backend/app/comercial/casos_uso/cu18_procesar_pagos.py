"""CU-18 — Procesar pagos

Absorbe los antiguos CU-29 (Pagar mediante pasarela digital), CU-30
(Procesar pago en caja) y CU-31 (Confirmar o rechazar transacción).

Actor: Cliente, Cajero, Sistema de pagos (actor externo).
Precondición: existe una venta pendiente de pago: digital (CU-13), para la
pasarela, o presencial (CU-14), para cobrar en caja con un cajero registrado
como empleado; para confirmar o rechazar, existe un pago en estado
'iniciado' con esa referencia de pasarela.
Postcondición: el pago queda aprobado o rechazado; si se aprueba, la venta
pasa a pagada y se actualiza el inventario de la sucursal (se descuenta el
stock); si se rechaza, se anula.

Caso de uso COMPUESTO: agrupa pagar mediante la pasarela digital (incluye
cancelar una compra que todavía no se pagó: libera el stock reservado y le
devuelve las prendas al carrito), procesar el pago en caja y confirmar o
rechazar la transacción (webhook real de Libélula/PayPal, polling activo de
estado, pantalla QR sandbox que reusa el mismo webhook para no duplicar la
resolución, y anular o reembolsar un pago ya aprobado).

También la clase de control `GestionarMetodoPagoGuardado`: el cliente autoriza
UNA vez, con conexión, que se le cobre con su PayPal (PayPal Vault v3) y el
servidor guarda solo el token que PayPal devuelve. Con él, el pedido sin
conexión (`RealizarPedidoDiferido`, CU-13) cobra al reconectar. Los datos de
tarjeta nunca pasan por aquí."""

import base64
import io
import json
import logging
import uuid
from decimal import Decimal
from html import escape

import qrcode
from qrcode.image.pil import PilImage
from sqlalchemy.orm import Session

from app.comercial.models import MetodoPagoGuardado, Pago, TransaccionPasarela
from app.comercial.pasarela import QrOnlineGateway, obtener_pasarela
from app.comercial.politicas import (
    anular_venta,
    cancelar_venta_pendiente,
    cerrar_pagos_iniciados,
    cobrar_en_caja,
    empresa_de_transaccion,
    enmascarar_correo,
    finalizar_reembolsos,
    obtener_comprobante,
    obtener_estado_codigo,
    obtener_venta,
    obtener_venta_bloqueada,
    primera_transaccion,
    procesar_reembolso,
    reembolsar_pago_completo,
    resolver_pago,
)
from app.comercial.repository import (
    EstadoPagoRepository,
    MetodoPagoGuardadoRepository,
    MetodoPagoRepository,
    PagoRepository,
    ReembolsoRepository,
    TransaccionPasarelaRepository,
)
from app.comercial.schemas import (
    MetodoPagoPayPalConfirmar,
    MetodoPagoPayPalIniciar,
    MetodoPagoPayPalIniciarRespuesta,
    MetodoPagoPayPalRespuesta,
    PagoCajaRequest,
    PagoIniciarRequest,
)
from app.core import paypal
from app.core.auditoria import (
    ACCION_ANULAR_PAGO,
    ACCION_GUARDAR,
    ACCION_QUITAR,
    ENTIDAD_METODO_PAGO_GUARDADO,
    ENTIDAD_VENTA,
    ContextoAuditoria,
)
from app.core.config import get_settings
from app.core.exceptions import (
    ConflictoError,
    DemasiadosIntentosError,
    DomainError,
    ErrorFuncional,
    NoEncontradoError,
    PermisoDenegadoError,
)
from app.core.rate_limit import limitador_paypal_guardado
from app.core.tenant import fijar_empresa
from app.core.tiempo import ahora_utc_naive
from app.plataforma import politicas as plataforma_politicas

logger = logging.getLogger(__name__)


# ---- Pagar mediante pasarela digital (antiguo CU-29) ----

class PagarPasarelaDigital:
    def __init__(self) -> None:
        self._metodos = MetodoPagoRepository()
        self._estados = EstadoPagoRepository()
        self._pagos = PagoRepository()
        self._transacciones = TransaccionPasarelaRepository()

    def iniciar(self, db: Session, usuario_id: int, datos: PagoIniciarRequest) -> tuple[Pago, str]:
        obtener_comprobante(db, datos.venta_id, usuario_id)  # valida dueño o staff, 404 si no existe

        # Bloquea la fila de la venta ANTES de decidir si se puede iniciar
        # un pago nuevo: serializa esta validación con cualquier otro
        # iniciar/confirmar_venta/anular_venta concurrente sobre la misma
        # venta (mismo patrón de lock que inventario usa para stock). Sin
        # esto, dos requests casi simultáneas (doble click, retry con otro
        # método de pago) pueden pasar la validación de "sin pago activo"
        # antes de que ninguna comitee, y terminar cobrando DOS veces de
        # verdad en la pasarela externa.
        venta = obtener_venta_bloqueada(db, datos.venta_id)
        estado_venta_actual = obtener_estado_codigo(db, venta.estado_id)
        if estado_venta_actual != "pendiente_pago":
            raise ConflictoError(f"La venta está '{estado_venta_actual}', no se puede iniciar un pago")

        metodo = self._metodos.obtener_por_codigo(db, datos.metodo_pago)
        if not metodo.requiere_pasarela:
            raise DomainError(f"'{metodo.codigo}' no es un método por pasarela, usá /pagos/caja")

        # Un pago 'iniciado' que nunca se completó (la pasarela lo denegó,
        # el cliente cerró la ventana) bloqueaba la venta para siempre: se
        # reemplaza, salvo que en realidad ya se haya cobrado.
        if cerrar_pagos_iniciados(db, venta.id, motivo="reemplazado_por_reintento"):
            raise ConflictoError("Esta venta ya fue pagada")

        estado_iniciado = self._estados.obtener_por_codigo(db, "iniciado")
        pago = Pago(venta_id=venta.id, metodo_pago_id=metodo.id, estado_id=estado_iniciado.id, monto=venta.total)
        self._pagos.crear(db, pago)  # flush: pago.id ya disponible

        pasarela = obtener_pasarela(metodo.codigo)
        try:
            resultado = pasarela.iniciar_pago(monto=venta.total, referencia=venta.codigo)
        except RuntimeError as exc:
            # No deja el pago en 'iniciado' colgado si la pasarela real (p.
            # ej. PayPal) no respondió: no tiene una transacción real detrás.
            db.rollback()
            raise DomainError(str(exc)) from exc
        pago.referencia_externa = resultado.id_transaccion

        payload_envio = {"monto": str(venta.total), "referencia": venta.codigo}
        if resultado.monto_usd is not None:  # PayPal cobra en dólares: queda la conversión que se hizo
            payload_envio["monto_usd"] = str(resultado.monto_usd)
        payload_respuesta = {"id_transaccion": resultado.id_transaccion, "url_redireccion": resultado.url_redireccion}
        self._transacciones.crear(
            db,
            TransaccionPasarela(
                pago_id=pago.id,
                pasarela=metodo.codigo,
                id_transaccion=resultado.id_transaccion,
                payload_envio=payload_envio,
                payload_respuesta=payload_respuesta,
                estado="iniciado",
            ),
        )

        db.commit()
        db.refresh(pago)
        return pago, resultado.url_redireccion

    def cancelar(self, db: Session, usuario_id: int, venta_id: int) -> None:
        """El cliente abandona una compra que todavía no pagó: libera el
        stock reservado y le devuelve las prendas al carrito."""
        obtener_comprobante(db, venta_id, usuario_id)  # valida dueño o staff, 404 si no existe
        cancelar_venta_pendiente(db, venta_id, motivo="cancelado_por_cliente")


# ---- Procesar pago en caja (antiguo CU-30) ----

class ProcesarPagoCaja:
    def ejecutar(self, db: Session, usuario_id: int, datos: PagoCajaRequest) -> tuple[Pago, Decimal | None]:
        # La lógica vive en comercial.politicas.cobrar_en_caja, para que la
        # sincronización offline (CU-25) cobre dentro de su propia unidad de trabajo.
        return cobrar_en_caja(
            db, usuario_id, datos.venta_id, datos.metodo_pago, datos.monto_recibido, commit=True
        )


# ---- Confirmar o rechazar transacción (antiguo CU-31) ----

class ConfirmarRechazarTransaccion:
    def __init__(self) -> None:
        self._estados = EstadoPagoRepository()
        self._pagos = PagoRepository()
        self._transacciones = TransaccionPasarelaRepository()

    def procesar_webhook(self, db: Session, pasarela_codigo: str, payload_crudo: bytes, firma: str | None) -> Pago:
        # `pasarela_codigo` viene de la URL (path param), sin validar contra
        # la base -- a diferencia de `PagarPasarelaDigital`, que ya lo saca de un
        # metodo_pago existente. Acá si no es una pasarela real, es un 404,
        # no un error 500.
        try:
            pasarela = obtener_pasarela(pasarela_codigo)
        except ValueError as exc:
            raise NoEncontradoError(f"No existe la pasarela '{pasarela_codigo}'") from exc

        if not pasarela.verificar_firma(payload_crudo, firma):
            raise PermisoDenegadoError("Firma de webhook inválida")

        try:
            payload = json.loads(payload_crudo)
        except json.JSONDecodeError as exc:
            raise ConflictoError("El body del webhook no es JSON válido") from exc

        resultado = pasarela.interpretar_webhook(payload)

        # Sin usuario ni token: la empresa sale de la transacción (ya con la
        # firma validada). Desconocida: la respuesta de siempre, 404.
        empresa_id = empresa_de_transaccion(db, pasarela_codigo, resultado.id_transaccion)
        if empresa_id is None:
            raise NoEncontradoError(f"No hay ningún pago iniciado con id_transaccion '{resultado.id_transaccion}'")
        fijar_empresa(db, empresa_id)

        transaccion_original = self._transacciones.obtener_por_id_transaccion(
            db, pasarela_codigo, resultado.id_transaccion
        )
        if transaccion_original is None:
            raise NoEncontradoError(f"No hay ningún pago iniciado con id_transaccion '{resultado.id_transaccion}'")

        return resolver_pago(
            db,
            transaccion_original.pago_id,
            pasarela_codigo=pasarela_codigo,
            id_transaccion=resultado.id_transaccion,
            estado_resultado=resultado.estado,
            payload_respuesta=payload,
            commit=True,
        )

    def obtener_estado(self, db: Session, usuario_id: int, pago_id: int) -> Pago:
        pago = self._pagos.obtener(db, pago_id)
        obtener_comprobante(db, pago.venta_id, usuario_id)  # valida dueño o staff, 404 si no existe

        estado_actual = self._estados.obtener(db, pago.estado_id)
        if estado_actual.codigo != "iniciado":
            return pago

        # Todavía no llegó (o nunca llegó) el webhook: pregunta activamente
        # a la pasarela, por si acá se enteran antes que por webhook.
        primera = primera_transaccion(db, pago.id)
        if primera is None or primera.id_transaccion is None:
            return pago

        pasarela = obtener_pasarela(primera.pasarela)
        try:
            estado_pasarela = pasarela.consultar_estado(primera.id_transaccion)
        except RuntimeError:
            # Best-effort: si la pasarela real no responde ahora, se
            # devuelve el último estado guardado en vez de romper el
            # polling del cliente.
            return pago
        if estado_pasarela == "iniciado":
            return pago  # sin novedad

        return resolver_pago(
            db,
            pago.id,
            pasarela_codigo=primera.pasarela,
            id_transaccion=primera.id_transaccion,
            estado_resultado=estado_pasarela,
            payload_respuesta={"origen": "consultar_estado", "estado": estado_pasarela},
            commit=True,
        )

    def anular(
        self,
        db: Session,
        usuario_id: int,
        pago_id: int,
        contexto: ContextoAuditoria | None = None,
        programar_envio=None,
    ) -> Pago:
        """El permiso ('pagos.gestionar') ya lo gatea el router, como el
        resto de las acciones de staff en este proyecto -- acá no se
        revalida. Sí se valida que la venta sea de la sucursal del empleado
        (anular reingresa stock en esa sucursal).

        Anular DEVUELVE EL DINERO de verdad: crea el reembolso de lo que falte por devolver de este pago (lo ya devuelto
        en devoluciones se descuenta) y el pago pasa a `reembolsado` solo cuando ese dinero salió. En efectivo y en los
        métodos de la tienda sale en el acto; en una pasarela se pide ya con la anulación confirmada, y si la pasarela
        no responde el reembolso queda `pendiente` (o `fallido`) para reintentarlo, sin deshacer la anulación."""
        pago = self._pagos.obtener_bloqueado(db, pago_id)  # mismo lock que resolver_pago: evita pisar un webhook concurrente
        venta = obtener_venta(db, pago.venta_id)
        plataforma_politicas.validar_acceso_sucursal(db, usuario_id, venta.sucursal_id)
        estado_actual = self._estados.obtener(db, pago.estado_id)
        if estado_actual.codigo != "aprobado":
            raise ConflictoError(f"Solo se puede anular un pago 'aprobado' (está '{estado_actual.codigo}')")

        estado_venta_anterior = obtener_estado_codigo(db, venta.estado_id)

        anular_venta(db, pago.venta_id, commit=False)
        reembolso = reembolsar_pago_completo(db, venta=venta, pago=pago, usuario_id=usuario_id, contexto=contexto)

        # Se audita aquí y no en `anular_venta`: esa función también la llaman el
        # vencimiento automático y el rechazo de la pasarela, que no son acciones
        # de una persona. Misma transacción que la anulación.
        plataforma_politicas.registrar_bitacora_de(
            db,
            contexto,
            ENTIDAD_VENTA,
            pago.venta_id,
            ACCION_ANULAR_PAGO,
            {"pago_id": pago.id, "estado_anterior": estado_venta_anterior},
        )
        db.commit()
        db.refresh(pago)
        if reembolso is not None:
            # Con la anulación ya confirmada: mueve el dinero de pasarela y manda la constancia al comprador. Nunca lanza.
            finalizar_reembolsos(db, [reembolso], contexto=contexto, programar_envio=programar_envio)
            db.refresh(pago)
        return pago

    # ---- QR online: pantalla pública de "pago" -----------------------------
    # Sin autenticación JWT en ninguna de las dos funciones de acá: el
    # id_transaccion (128 bits, ver QrOnlineGateway.iniciar_pago) es el
    # único requisito para verlas/usarlas, igual modelo de confianza que un
    # link de pago o que el propio webhook de las otras pasarelas.

    def _generar_qr_base64(self, contenido: str) -> str:
        # Fábrica de PIL explícita: es la que usa qrcode[pil] y la única cuyo save() acepta `format`.
        imagen = qrcode.make(contenido, image_factory=PilImage)
        buffer = io.BytesIO()
        imagen.save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode("ascii")

    def _plantilla_pantalla_qr(
        self, *, id_transaccion: str, monto: Decimal, imagen_qr_base64: str, ya_resuelto: bool, estado_codigo: str
    ) -> str:
        if ya_resuelto:
            cuerpo_accion = (
                f'<p class="estado">Este pago ya quedó registrado como <strong>{escape(estado_codigo)}</strong>. '
                "Podés cerrar esta pantalla.</p>"
            )
        else:
            cuerpo_accion = f"""
            <button id="btn-confirmar" onclick="confirmar()">Confirmar pago</button>
            <p id="mensaje" class="estado"></p>
            <script>
              function confirmar() {{
                const boton = document.getElementById('btn-confirmar');
                const mensaje = document.getElementById('mensaje');
                boton.disabled = true;
                boton.textContent = 'Confirmando...';
                fetch(window.location.pathname + '/confirmar', {{ method: 'POST' }})
                  .then((resp) => {{
                    if (!resp.ok) throw new Error('fallo');
                    boton.textContent = 'Pago confirmado';
                    mensaje.textContent = '¡Pago confirmado! Ya podés volver a la aplicación.';
                  }})
                  .catch(() => {{
                    boton.disabled = false;
                    boton.textContent = 'Confirmar pago';
                    mensaje.textContent = 'No se pudo confirmar. Probá de nuevo.';
                  }});
              }}
            </script>
            """
        return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pagar con QR - FashionStore</title>
<style>
  body {{ background: #EAE4DA; color: #1C1713; font-family: system-ui, sans-serif;
         display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; padding: 16px; }}
  .tarjeta {{ background: #FFFFFF; border: 1px solid #DBD0C1; border-radius: 18px;
             padding: 32px; max-width: 360px; width: 100%; text-align: center; }}
  h1 {{ font-size: 20px; margin: 0 0 4px; }}
  .monto {{ font-size: 28px; font-weight: 700; margin: 4px 0 20px; }}
  img {{ width: 220px; height: 220px; margin-bottom: 20px; }}
  button {{ background: #9A3E1F; color: #fff; border: none; border-radius: 6px;
           padding: 12px 24px; font-size: 16px; cursor: pointer; width: 100%; }}
  button:disabled {{ opacity: .6; cursor: default; }}
  .estado {{ color: #6E6156; font-size: 14px; margin-top: 12px; }}
  .transaccion {{ color: #C7BCAC; font-size: 11px; margin-top: 20px; }}
</style>
</head>
<body>
  <div class="tarjeta">
    <h1>Pagar con QR</h1>
    <div class="monto">Bs {escape(str(monto))}</div>
    <img src="data:image/png;base64,{imagen_qr_base64}" alt="Código QR de pago">
    {cuerpo_accion}
    <div class="transaccion">{escape(id_transaccion)}</div>
  </div>
</body>
</html>"""

    def renderizar_pantalla_qr(self, db: Session, id_transaccion: str) -> str:
        """GET /pagos/qr/{id}: pantalla pública (sin login) con el QR y el
        botón de confirmar. El QR codifica esta misma URL -- se puede abrir
        directo (mismo dispositivo del checkout) o escanear con otro
        celular."""
        empresa_id = empresa_de_transaccion(db, "qr_online", id_transaccion)
        if empresa_id is None:
            raise NoEncontradoError("Transacción QR no encontrada")
        fijar_empresa(db, empresa_id)
        transaccion = self._transacciones.obtener_por_id_transaccion(db, "qr_online", id_transaccion)
        if transaccion is None:
            raise NoEncontradoError("Transacción QR no encontrada")
        pago = self._pagos.obtener(db, transaccion.pago_id)
        estado = self._estados.obtener(db, pago.estado_id)

        base_url = get_settings().backend_public_url.rstrip("/")
        url_pantalla = f"{base_url}/api/v1/pagos/qr/{id_transaccion}"

        return self._plantilla_pantalla_qr(
            id_transaccion=id_transaccion,
            monto=pago.monto,
            imagen_qr_base64=self._generar_qr_base64(url_pantalla),
            ya_resuelto=estado.codigo != "iniciado",
            estado_codigo=estado.codigo,
        )

    def confirmar_pago_qr(self, db: Session, id_transaccion: str) -> Pago:
        """POST /pagos/qr/{id}/confirmar: lo llama el botón de la pantalla
        de arriba. Arma el mismo payload+firma que mandaría un webhook real
        y lo procesa por procesar_webhook(): reusa toda la idempotencia/
        auditoría ya probada para Libélula/PayPal en vez de duplicar la
        resolución acá.

        La empresa la fija `procesar_webhook` desde la transacción (después
        de validar la firma); un id desconocido responde 404 como siempre."""
        payload = json.dumps({"id_transaccion": id_transaccion, "estado": "aprobado"}).encode("utf-8")
        firma = QrOnlineGateway().firmar_confirmacion(payload)
        return self.procesar_webhook(db, "qr_online", payload, firma)


# ---- Reembolsos: consultar y reintentar ----

class GestionarReembolsos:
    """El dinero devuelto a quien compró. Los reembolsos NACEN en las devoluciones sin cambio de prenda (CU-17) y al
    anular un pago (`ConfirmarRechazarTransaccion.anular`); aquí solo se consultan y se reintentan los que la pasarela no
    pudo hacer. La lógica (montos, tope por pago, pasarela, avisos) vive en `comercial.politicas`."""

    def __init__(self) -> None:
        self._reembolsos = ReembolsoRepository()

    def listar_de_venta(self, db: Session, usuario_id: int, venta_id: int) -> list:
        """Los reembolsos de una venta: los ve quien compró o el personal de su sucursal (misma regla que el
        comprobante: otra persona recibe 404, igual que si la venta no existiera)."""
        obtener_comprobante(db, venta_id, usuario_id)
        return self._reembolsos.listar_por_venta(db, venta_id)

    def reintentar(
        self,
        db: Session,
        usuario_id: int,
        reembolso_id: int,
        contexto: ContextoAuditoria | None = None,
        programar_envio=None,
    ):
        """Vuelve a pedirle a la pasarela un reembolso `pendiente` (no respondió) o `fallido` (lo rechazó), con la misma
        clave de idempotencia: si la pasarela sí lo había hecho, no devuelve el dinero dos veces. Solo el personal de la
        sucursal de la venta (o el administrador). Si sale, el comprador recibe su constancia."""
        reembolso = self._reembolsos.obtener(db, reembolso_id)
        plataforma_politicas.validar_acceso_sucursal(db, usuario_id, reembolso.sucursal_id)
        if reembolso.estado == "reembolsado":
            raise ConflictoError("Este reembolso ya se hizo")
        resultado = procesar_reembolso(db, reembolso_id, contexto=contexto)
        if resultado.estado == "reembolsado":
            finalizar_reembolsos(db, [resultado], contexto=contexto, programar_envio=programar_envio)
            db.refresh(resultado)
        return resultado


# ---- PayPal guardado del cliente (Vault v3) ----


def _paypal_no_disponible() -> ErrorFuncional:
    return ErrorFuncional(
        "paypal_no_disponible", "PayPal no está disponible por ahora. Intenta de nuevo en unos minutos.", 503
    )


def _respuesta_metodo(fila: MetodoPagoGuardado | None) -> MetodoPagoPayPalRespuesta:
    if fila is None or fila.estado != "activo":
        return MetodoPagoPayPalRespuesta(guardado=False)
    return MetodoPagoPayPalRespuesta(guardado=True, correo_paypal=fila.correo_paypal, guardado_en=fila.confirmado_en)


class GestionarMetodoPagoGuardado:
    """Guardar, consultar y quitar el PayPal del cliente. El flujo es en dos pasos, siempre CON conexión:

    1. `iniciar`: crea el setup token en PayPal y una fila `pendiente`; el cliente aprueba en PayPal.
    2. `confirmar`: cambia el setup token (el `approval_token_id` con el que PayPal vuelve) por el payment token y lo
       deja `activo`. Solo hay UN método activo por usuario: guardar otro revoca el anterior (en PayPal, mejor esfuerzo).

    El correo de PayPal se guarda y se devuelve ENMASCARADO. Los tokens no salen nunca en una respuesta ni en la
    bitácora. Por qué aquí y no en un CU nuevo: es parte de procesar pagos (CU-18)."""

    def __init__(self) -> None:
        self._metodos = MetodoPagoGuardadoRepository()

    def consultar(self, db: Session, usuario_id: int) -> MetodoPagoPayPalRespuesta:
        return _respuesta_metodo(self._metodos.obtener_activo(db, usuario_id))

    def iniciar(
        self, db: Session, usuario_id: int, datos: MetodoPagoPayPalIniciar
    ) -> MetodoPagoPayPalIniciarRespuesta:
        clave = str(usuario_id)
        espera = limitador_paypal_guardado.bloqueado(clave)
        if espera is not None:
            raise DemasiadosIntentosError(espera, "Intentaste guardar tu PayPal muchas veces. Intenta más tarde.")
        limitador_paypal_guardado.registrar_fallo(clave)  # cuenta cada inicio (no es un "fallo")

        # Las URLs de retorno las arma el servidor (nunca el cliente): la web y la app (WebView) interceptan esta misma.
        empresa = plataforma_politicas.obtener_empresa_de_la_sesion(db)
        retorno = f"{get_settings().frontend_public_url.rstrip('/')}/t/{empresa.codigo}/mi-cuenta/paypal-guardado"
        try:
            setup = paypal.crear_setup_token(
                return_url=retorno, cancel_url=f"{retorno}?cancelado=1", request_id=uuid.uuid4().hex
            )
        except paypal.PayPalError as exc:
            logger.warning("paypal_guardado_no_iniciado estado_http=%s", exc.status_code)
            raise _paypal_no_disponible() from exc

        ahora = ahora_utc_naive()
        for previa in self._metodos.listar_pendientes(db, usuario_id):  # un intento nuevo cancela los anteriores
            previa.estado = "revocado"
            previa.revocado_en = ahora
        self._metodos.crear(
            db, MetodoPagoGuardado(usuario_id=usuario_id, proveedor="paypal", estado="pendiente", setup_token_id=setup.id)
        )
        db.commit()
        return MetodoPagoPayPalIniciarRespuesta(url_aprobacion=setup.url_aprobacion, token_preparacion=setup.id)

    def confirmar(
        self,
        db: Session,
        usuario_id: int,
        datos: MetodoPagoPayPalConfirmar,
        contexto: ContextoAuditoria | None = None,
    ) -> MetodoPagoPayPalRespuesta:
        # Solo el token de ESTE usuario: el de otra persona, uno inexistente o uno ya descartado se ven igual (404).
        # Bloqueada (PostgreSQL): dos confirmaciones simultáneas se ponen en fila y la segunda ve el resultado.
        fila = self._metodos.obtener_por_setup_token(db, usuario_id, datos.token_preparacion, bloquear=True)
        if fila is None or fila.estado == "revocado":
            raise NoEncontradoError("Token de preparación no encontrado")
        if fila.estado == "activo":
            return _respuesta_metodo(fila)  # idempotente: ya estaba confirmado

        try:
            creado = paypal.crear_payment_token(fila.setup_token_id)
        except paypal.PayPalError as exc:
            logger.warning("paypal_guardado_no_confirmado estado_http=%s", exc.status_code)
            if exc.status_code in (400, 404, 422):  # PayPal entendió la petición y la negó: el cliente no aprobó
                raise ErrorFuncional(
                    "paypal_no_aprobado",
                    "No terminaste de aprobar tu PayPal. Intenta guardarlo de nuevo.",
                    409,
                ) from exc
            raise _paypal_no_disponible() from exc

        ahora = ahora_utc_naive()
        anterior = self._metodos.obtener_activo(db, usuario_id, bloquear=True)
        token_anterior = None
        if anterior is not None:  # reemplazo: el índice único deja UN solo activo, así que se revoca primero
            token_anterior = anterior.payment_token_id
            anterior.estado = "revocado"
            anterior.revocado_en = ahora
            db.flush()
        fila.estado = "activo"
        fila.payment_token_id = creado.id
        fila.correo_paypal = enmascarar_correo(creado.correo)
        fila.confirmado_en = ahora
        plataforma_politicas.registrar_bitacora_de(
            db, contexto, ENTIDAD_METODO_PAGO_GUARDADO, fila.id, ACCION_GUARDAR, {"reemplazo": anterior is not None}
        )
        db.commit()
        db.refresh(fila)
        self._revocar_en_paypal(token_anterior)
        return _respuesta_metodo(fila)

    def quitar(self, db: Session, usuario_id: int, contexto: ContextoAuditoria | None = None) -> None:
        """Idempotente: sin nada guardado no hace nada. Revoca el token en PayPal (mejor esfuerzo: si PayPal no
        responde, igual queda revocado aquí y no se le vuelve a cobrar) y descarta los intentos pendientes."""
        ahora = ahora_utc_naive()
        token = None
        activo = self._metodos.obtener_activo(db, usuario_id, bloquear=True)
        if activo is not None:
            token = activo.payment_token_id
            activo.estado = "revocado"
            activo.revocado_en = ahora
        pendientes = self._metodos.listar_pendientes(db, usuario_id)
        for fila in pendientes:
            fila.estado = "revocado"
            fila.revocado_en = ahora
        if activo is not None:
            plataforma_politicas.registrar_bitacora_de(
                db, contexto, ENTIDAD_METODO_PAGO_GUARDADO, activo.id, ACCION_QUITAR, {}
            )
        db.commit()
        self._revocar_en_paypal(token)

    @staticmethod
    def _revocar_en_paypal(payment_token_id: str | None) -> None:
        """Mejor esfuerzo: un fallo de PayPal no deshace nada (el token ya quedó revocado en la base)."""
        if not payment_token_id:
            return
        try:
            paypal.borrar_payment_token(payment_token_id)
        except paypal.PayPalError as exc:
            logger.warning("paypal_token_no_revocado estado_http=%s", exc.status_code)
