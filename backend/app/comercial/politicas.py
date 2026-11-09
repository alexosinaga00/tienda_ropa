"""Reglas y operaciones internas del paquete `comercial` (reservas, ventas, pagos y
entregas) que no son casos de uso del catálogo. Reservas:
- `validar_transicion` (antes `_transicionar`): valida y aplica un cambio
  de estado, registrando el historial. La usan varios
  controladores de CU-12 (reservar, cancelar, atender): no se duplica.
- `validar_propietario_o_staff`: valida acceso a una reserva (el personal,
  solo a las de su sucursal). La usan varios controladores de CU-12.
- `expirar_reservas_vencidas`: tarea programada sin actor humano, expuesta
  por un endpoint protegido con token de servicio.
- `mapa_codigos_estado_reserva`, `obtener_reserva_para_venta` y
  `reporte_reservas_por_estado`: consultas que el router, la sección de Ventas y `inteligencia`
  (reportes) necesitan sin tocar las tablas de reservas directamente.

Ventas: `registrar_venta`, `confirmar_venta` y `anular_venta` (compartidas por la
compra digital, la venta presencial y los pagos), el cálculo de precio con
promoción y las consultas de ventas para reportes. Pagos: `expirar_ventas_pendientes`.
Las entregas reutilizan `obtener_comprobante` para validar el acceso a la venta.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from html import escape
from typing import TYPE_CHECKING
from urllib.parse import quote

from sqlalchemy import event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.catalogo import politicas as catalogo_politicas
from app.catalogo.casos_uso.cu09_gestionar_inventario import ConsultarDisponibilidadSucursal
from app.comercial import repository as comercial_repo
from app.comercial.models import (
    CajaTurno,
    Carrito,
    CarritoDetalle,
    Devolucion,
    EstadoVenta,
    MetodoPago,
    Pago,
    Promocion,
    Reembolso,
    Reserva,
    ReservaDetalle,
    ReservaHistorial,
    TransaccionPasarela,
    Venta,
    VentaDetalle,
)
from app.comercial.pasarela import ReembolsoRechazado, obtener_pasarela
from app.comercial.repository import (
    CajaTurnoRepository,
    CarritoRepository,
    DevolucionRepository,
    EstadoPagoRepository,
    EstadoReservaRepository,
    EstadoVentaRepository,
    MetodoPagoRepository,
    PagoRepository,
    PromocionRepository,
    ReembolsoRepository,
    ReservaRepository,
    TransaccionPasarelaRepository,
    VentaRepository,
)
from app.comercial.schemas import (
    PagoRespuesta,
    ReembolsoRespuesta,
    ReservaCrear,
    ResumenTurnoRespuesta,
    SolicitudCambioLineaRespuesta,
    SolicitudCambioRespuesta,
    TurnoAbrir,
    TurnoCerrar,
    TurnoCompletarConteo,
    TurnoDetalleRespuesta,
    TurnoRespuesta,
)
from app.core.auditoria import (
    ACCION_ABRIR,
    ACCION_CERRAR,
    ACCION_CIERRE_AUTOMATICO,
    ACCION_COMPLETAR_CONTEO,
    ACCION_FALLAR,
    ACCION_REEMBOLSAR,
    ENTIDAD_CIERRE_CAJA,
    ENTIDAD_REEMBOLSO,
    ContextoAuditoria,
)
from app.core.config import get_settings
from app.core.codigos import generar_codigo
from app.core.permisos import (
    PERMISO_CAJA_SUPERVISAR,
    PERMISO_STAFF_RESERVAS,
    PERMISO_STAFF_VENTAS,
    PERMISO_VENTAS_PRESENCIAL,
)
from app.core.deps import ParametrosPeriodo
from app.core.correo import MensajeCorreo, enviar_correo_sin_romper
from app.core.correo import envio_configurado as correo_configurado
from app.core.tiempo import ZONA_BOLIVIA, ahora_utc_naive, dia_bolivia, hoy_utc
from app.core.exceptions import (
    ConflictoError,
    DomainError,
    ErrorFuncional,
    NoEncontradoError,
    PermisoDenegadoError,
    PlazoCambioVencidoError,
    StockInsuficienteError,
)
from app.core.repository import confirmar
from app.core.security import permisos_de_usuario
from app.core.tenant import fijar_empresa, por_cada_empresa, sin_filtro
from app.plataforma import politicas as plataforma_politicas
from app.plataforma.politicas import obtener_perfil_cliente


# ---- Reservas ----


logger = logging.getLogger(__name__)


def _cerrar_tx(db: Session, entidad: object, commit: bool) -> None:
    """Cierra una escritura de las transiciones de estado de reservas, ventas
    y pagos: `commit=True` confirma y refresca `entidad` (queda lista para
    responder); `commit=False` solo hace flush y NO refresca, porque quien
    llama es dueño de la transacción. Las escrituras que crean filas
    (`registrar_venta`, `crear_reserva`, `cobrar_en_caja`) refrescan SIEMPRE,
    para leer los defaults del servidor, así que no pasan por acá."""
    confirmar(db, commit)
    if commit:
        db.refresh(entidad)


estado_reserva_repo = EstadoReservaRepository()
reserva_repo = ReservaRepository()

# Transiciones válidas iniciadas por una persona (staff). 'expirada' no
# está acá a propósito: solo la genera expirar_reservas_vencidas(), nunca
# un PUT.
TRANSICIONES_VALIDAS: dict[str, set[str]] = {
    "pendiente": {"preparada", "cancelada"},
    "preparada": {"en_prueba", "cancelada"},
    "en_prueba": {"completada"},
}


def es_staff(db: Session, usuario_id: int) -> bool:
    return PERMISO_STAFF_RESERVAS in permisos_de_usuario(db, usuario_id)


def validar_propietario_o_staff(db: Session, reserva: Reserva, usuario_id: int) -> None:
    if es_staff(db, usuario_id):
        # El personal solo accede a las reservas de su propia sucursal.
        plataforma_politicas.validar_acceso_sucursal(db, usuario_id, reserva.sucursal_id)
        return
    cliente = obtener_perfil_cliente(db, usuario_id)
    if cliente is None or reserva.cliente_id != cliente.id:
        raise PermisoDenegadoError("No tenés acceso a esta reserva")


def validar_transicion(
    db: Session, reserva: Reserva, codigo_nuevo: str, usuario_id: int | None, comentario: str, commit: bool = True
) -> Reserva:
    estado_actual = estado_reserva_repo.obtener(db, reserva.estado_id)
    validos = TRANSICIONES_VALIDAS.get(estado_actual.codigo, set())
    if codigo_nuevo not in validos:
        raise DomainError(f"No se puede pasar de '{estado_actual.codigo}' a '{codigo_nuevo}'")

    estado_nuevo = estado_reserva_repo.obtener_por_codigo(db, codigo_nuevo)
    reserva.estado_id = estado_nuevo.id
    db.add(
        ReservaHistorial(
            reserva_id=reserva.id, estado_id=estado_nuevo.id, usuario_id=usuario_id, comentario=comentario
        )
    )
    _cerrar_tx(db, reserva, commit)
    return reserva


def crear_reserva(
    db: Session,
    usuario_id: int,
    datos: ReservaCrear,
    commit: bool = True,
    *,
    cliente_id: int | None = None,
    creado_en: dt.datetime | None = None,
) -> Reserva:
    """Crea una reserva con el stock de cada línea apartado y avisa a la
    sucursal. Es la lógica de `ReservarPrendas` (CU-12), extraída para que la
    sincronización offline (CU-25) la use dentro de su propia unidad de
    trabajo.

    `commit=False`: deja todo en flush (reserva, historial, stock apartado y
    notificaciones) y NO confirma; quien llama decide el commit o el rollback
    de todo el lote. Si una línea no tiene disponibilidad suficiente, se
    lanza el error y nada de lo anterior debe confirmarse (con commit=True el
    error propaga y get_db revierte; con commit=False es responsabilidad del
    llamador hacer rollback). Los bloqueos de stock se toman en orden
    (variante_id, sucursal_id) con `bloquear_stock_en_orden`.

    Solo para la sincronización offline (CU-25), ambos opcionales:
    - `cliente_id`: la reserva la registra el PERSONAL a nombre de ese cliente
      (404 si no existe). `usuario_id` sigue siendo el ACTOR (historial y
      notificaciones). Sin él, el cliente es el perfil del usuario logueado.
    - `creado_en`: la fecha REAL de la reserva (UTC naive). Sin ella, la de la base."""
    if cliente_id is not None:
        cliente = plataforma_politicas.obtener_cliente(db, cliente_id)
    else:
        cliente = obtener_perfil_cliente(db, usuario_id)
    plataforma_politicas.obtener_sucursal(db, datos.sucursal_id)  # 404 si no existe
    plataforma_politicas.validar_horario_en_atencion(
        db, datos.sucursal_id, datos.fecha_visita, datos.hora_visita_desde, datos.hora_visita_hasta
    )

    for linea in datos.detalle:
        catalogo_politicas.obtener_variante(db, linea.variante_id)  # 404 si no existe

    estado_pendiente = estado_reserva_repo.obtener_por_codigo(db, "pendiente")
    fecha_hasta = dt.datetime.combine(datos.fecha_visita, datos.hora_visita_hasta, tzinfo=dt.timezone.utc)
    fecha_expiracion = fecha_hasta + dt.timedelta(hours=24)

    reserva = Reserva(
        codigo=generar_codigo(db, "RES", reserva_repo.obtener_por_codigo),
        cliente_id=cliente.id,
        sucursal_id=datos.sucursal_id,
        estado_id=estado_pendiente.id,
        fecha_visita=datos.fecha_visita,
        hora_visita_desde=datos.hora_visita_desde,
        hora_visita_hasta=datos.hora_visita_hasta,
        fecha_expiracion=fecha_expiracion,
        observacion=datos.observacion,
        **({"creado_en": creado_en} if creado_en is not None else {}),
    )
    reserva.detalle = [
        ReservaDetalle(variante_id=linea.variante_id, cantidad=linea.cantidad) for linea in datos.detalle
    ]
    reserva_repo.crear(db, reserva)  # flush: reserva.id ya queda disponible

    # Reserva el stock de cada línea. Si una no tiene disponibilidad
    # suficiente, ninguna de las anteriores queda aplicada (commit=False:
    # toda la creación es una sola transacción).
    catalogo_politicas.bloquear_stock_en_orden(
        db, [(linea.variante_id, datos.sucursal_id) for linea in reserva.detalle]
    )
    for linea in reserva.detalle:
        catalogo_politicas.reservar_stock(db, linea.variante_id, datos.sucursal_id, linea.cantidad, commit=False)

    db.add(
        ReservaHistorial(
            reserva_id=reserva.id,
            estado_id=estado_pendiente.id,
            usuario_id=usuario_id,
            comentario="Reserva registrada por el personal" if cliente_id is not None else "Reserva creada",
        )
    )

    for empleado in plataforma_politicas.listar_empleados_sucursal(db, datos.sucursal_id):
        plataforma_politicas.crear_notificacion(
            db,
            empleado.usuario_id,
            titulo="Nueva reserva",
            mensaje=f"Reserva {reserva.codigo} para el {datos.fecha_visita.isoformat()}",
            tipo="reserva",
            referencia_id=reserva.id,
            commit=False,
        )

    confirmar(db, commit)
    db.refresh(reserva)
    return reserva


ESTADOS_RESERVA_CON_STOCK_APARTADO = ("pendiente", "preparada", "en_prueba")


def validar_topes_de_reserva_del_cliente(db: Session, usuario_id: int, datos: ReservaCrear) -> None:
    """Los topes de una reserva que hace el CLIENTE (no la que el personal registra sin conexión): la visita es de hoy a unos
    pocos días (hora de Bolivia), pocas unidades por prenda y en total, y pocas reservas abiertas a la vez. Sin ellos, un solo
    cliente podría dejar la tienda "agotada" apartando todo el stock con una visita muy lejana. `DomainError` (400)."""
    ajustes = get_settings()
    hoy = dia_bolivia()[0]
    if datos.fecha_visita < hoy:
        raise DomainError("La fecha de la visita ya pasó: elige hoy o un día próximo")
    limite = hoy + dt.timedelta(days=ajustes.reserva_max_dias_anticipacion)
    if datos.fecha_visita > limite:
        raise DomainError(
            f"Solo se puede reservar con hasta {ajustes.reserva_max_dias_anticipacion} días de anticipación "
            f"(hasta el {limite.isoformat()})"
        )
    for linea in datos.detalle:
        if linea.cantidad > ajustes.reserva_max_unidades_por_linea:
            raise DomainError(f"Una reserva admite hasta {ajustes.reserva_max_unidades_por_linea} unidades de cada prenda")
    if sum(linea.cantidad for linea in datos.detalle) > ajustes.reserva_max_unidades:
        raise DomainError(f"Una reserva admite hasta {ajustes.reserva_max_unidades} unidades en total")
    cliente = obtener_perfil_cliente(db, usuario_id)
    abiertas = reserva_repo.contar_abiertas_de_cliente(db, cliente.id, ESTADOS_RESERVA_CON_STOCK_APARTADO)
    if abiertas >= ajustes.reserva_max_activas_por_cliente:
        raise DomainError(
            f"Ya tienes {abiertas} reservas abiertas (el máximo es {ajustes.reserva_max_activas_por_cliente}): "
            "cancela una o espera a que se atienda"
        )


def mapa_codigos_estado_reserva(db: Session) -> dict[int, str]:
    """Para que el router arme ReservaRespuesta sin consultar
    `estado_reserva` directamente."""
    return estado_reserva_repo.mapa_codigos_por_id(db)


def obtener_reserva_para_venta(db: Session, reserva_id: int) -> Reserva:
    """Para que la sección de Ventas (venta presencial en caja) lea, sin consultar
    `reserva`/`reserva_detalle` directamente, las líneas que un cliente
    decidió comprar al probarse la reserva -- el cliente de la venta sale
    de `reserva.cliente_id`, no hace falta que el cajero ya lo conozca. Sin
    chequeo de propiedad: es una acción de staff, no del cliente dueño.
    CU-12 (registrar selección) ya deja la reserva en 'completada' en
    cuanto todas las líneas tienen decisión -- acá solo se valida que ese
    paso ya haya pasado.

    Bloquea la fila de la reserva: dos cajeros cobrando la misma reserva a
    la vez esperan uno al otro, y el segundo ve la venta del primero (la
    guardia de doble facturación vive en ventas, CU-14)."""
    reserva = reserva_repo.obtener_bloqueado(db, reserva_id)
    estado = estado_reserva_repo.obtener(db, reserva.estado_id)
    if estado.codigo != "completada":
        raise DomainError(f"La reserva está en estado '{estado.codigo}', todavía no se puede facturar")
    return reserva


def reporte_reservas_por_estado(
    db: Session, periodo: ParametrosPeriodo, sucursal_id: int | None = None
) -> list[dict]:
    """Para `inteligencia` (reportes): cantidad de reservas por estado en el
    período, sin saber nada de si terminaron en una venta -- esa cuenta
    cruzada la hace `inteligencia`, no acá."""
    return reserva_repo.contar_por_estado(db, periodo.desde, periodo.hasta, sucursal_id)


def expirar_reservas_vencidas(db: Session) -> int:
    """Libera el stock de todas las reservas vencidas que sigan en estado
    pendiente o preparada. Cada reserva se procesa (liberación + cambio de
    estado) como su propia transacción, así una reserva con datos raros no
    frena a las demás. No es un caso de uso del catálogo (no tiene actor
    humano): se expone por un endpoint protegido con token de servicio,
    pensado para ser llamado por un cron."""
    ahora = ahora_utc_naive()
    estados_activos_ids = [
        estado_reserva_repo.obtener_por_codigo(db, codigo).id for codigo in ("pendiente", "preparada")
    ]
    ids_vencidas = [reserva.id for reserva in reserva_repo.listar_vencidas(db, ahora, estados_activos_ids)]
    estado_expirada_id = estado_reserva_repo.obtener_por_codigo(db, "expirada").id

    expiradas = 0
    for reserva_id in ids_vencidas:
        try:
            # Bloqueada y con el estado releído: si el cliente la canceló (o
            # el personal la avanzó) mientras tanto, ya no se toca.
            reserva = reserva_repo.obtener_bloqueado(db, reserva_id)
            if reserva.estado_id not in estados_activos_ids:
                db.rollback()
                continue
            catalogo_politicas.bloquear_stock_en_orden(
                db, [(linea.variante_id, reserva.sucursal_id) for linea in reserva.detalle]
            )
            for linea in reserva.detalle:
                catalogo_politicas.liberar_stock(
                    db, linea.variante_id, reserva.sucursal_id, linea.cantidad, commit=False
                )
            reserva.estado_id = estado_expirada_id
            db.add(
                ReservaHistorial(
                    reserva_id=reserva.id,
                    estado_id=estado_expirada_id,
                    usuario_id=None,
                    comentario="Expirada automáticamente",
                )
            )
            db.commit()
            expiradas += 1
        except Exception:
            # Una reserva inconsistente (p. ej. menos stock reservado del que
            # dice su detalle) se deja como está y se registra, pero no frena
            # la expiración de las demás.
            db.rollback()
            logger.exception("No se pudo expirar la reserva %s", reserva_id)

    return expiradas


def expirar_reservas_de_todas_las_empresas(db: Session) -> int:
    """Corre `expirar_reservas_vencidas` una vez por cada empresa activa (con
    o sin suscripción vigente: liberar el stock apartado es mantenimiento,
    no una operación comercial) y suma lo expirado. Una empresa que falla no
    frena a las demás y no aporta a la suma. La sesión queda sin empresa."""
    resultados = por_cada_empresa(db, plataforma_politicas.listar_empresas_activas(db), expirar_reservas_vencidas)
    return sum(r for r in resultados if r is not None)


# ---- Ventas ----
# Corazón de la sección Ventas: registrar_venta() es la regla de negocio
# compartida por CU-13 (compra digital) y CU-14 (venta presencial) -- hace
# TODO en una sola transacción (una línea sin stock revierte la venta
# entera):
#
# 1. Valida disponibilidad de cada línea (vía catalogo.politicas, antes de
#    tocar nada).
# 2. Crea venta y venta_detalle, congelando `costo_unitario` desde
#    `stock.costo_promedio` recién en confirmar_venta() -- nunca se
#    recalcula después, aunque cambie el costo promedio real de la variante.
# 3. Llama a catalogo.politicas.actualizar_stock_operacion() tipo 'venta'
#    por cada línea (en confirmar_venta, cuando el pago se aprueba).
# 4. Si la venta viene de una reserva, libera el stock reservado de esa
#    línea antes del movimiento y usa las líneas que el cliente ya marcó
#    `seleccionada=True` al probarse (CU-12 ya deja la reserva en
#    'completada' en ese momento).
# 5. Aplica promociones vigentes según `promocion_alcance`: si más de una
#    promoción matchea la misma línea, se toma la de mayor descuento.
# 6. Calcula subtotal (bruto, antes de descuento), descuento, costo de
#    envío y total.
#
# confirmar_venta()/anular_venta() las dispara la sección de Pagos (CU-18)
# al aprobar o rechazar el pago: ninguna de las dos es un caso de uso propio
# del catálogo. marcar_venta_entregada() la dispara la sección de Entregas
# (CU-19) cuando el envío llega a 'entregado'. El resto de este archivo son
# consultas que las secciones de Pagos y Entregas y el paquete `inteligencia`
# (reportes y recomendador) necesitan sin tocar las tablas de ventas directamente.


if TYPE_CHECKING:
    from sqlalchemy import Select

    from app.catalogo.models import ProductoVariante

estado_venta_repo = EstadoVentaRepository()
venta_repo = VentaRepository()
promocion_repo = PromocionRepository()
carrito_repo = CarritoRepository()
devolucion_repo = DevolucionRepository()
_disponibilidad_cu = ConsultarDisponibilidadSucursal()

_DOS_DECIMALES = Decimal("0.01")


def redondear(valor: Decimal) -> Decimal:
    return valor.quantize(_DOS_DECIMALES, rounding=ROUND_HALF_UP)


# ---- Cálculo de precio + promoción ------------------------------------------------


def mejor_descuento(precio_unitario: Decimal, promociones: Iterable[Promocion]) -> Decimal:
    """El mayor descuento unitario entre las promociones dadas, SIN redondear (quien lo usa
    redondea): porcentaje del precio o monto fijo, y nunca más que el precio (el precio no queda
    negativo). Es la regla de `calcular_linea`, compartida con el paquete de descarga offline."""
    descuento_unitario = Decimal("0")
    for promocion in promociones:
        if promocion.tipo == "porcentaje":
            candidato = precio_unitario * promocion.valor / Decimal("100")
        else:
            candidato = promocion.valor
        candidato = min(candidato, precio_unitario)
        descuento_unitario = max(descuento_unitario, candidato)
    return descuento_unitario


def calcular_linea(db: Session, variante: ProductoVariante, cantidad: int, hoy: dt.date) -> tuple[Decimal, Decimal, Decimal]:
    """(precio_unitario, descuento_unitario, subtotal_neto) de una línea.
    La usan CU-13 (previsualizar el carrito) y registrar_venta (CU-13 y
    CU-14): no se duplica el cálculo de promoción en los dos lugares."""
    precio_unitario = catalogo_politicas.obtener_precio_efectivo(variante)
    producto_id, categoria_id, temporada_id = catalogo_politicas.obtener_info_promocion(variante)
    promociones = promocion_repo.listar_vigentes_para(
        db, producto_id=producto_id, categoria_id=categoria_id, temporada_id=temporada_id, hoy=hoy
    )

    descuento_unitario = redondear(mejor_descuento(precio_unitario, promociones))
    subtotal = redondear((precio_unitario - descuento_unitario) * cantidad)
    return precio_unitario, descuento_unitario, subtotal


def listar_promociones_vigentes(db: Session, hoy: dt.date) -> list[Promocion]:
    """Para `sincronizacion` (manifiesto del paquete offline): las promociones activas y vigentes
    hoy, con sus alcances. Es informativa: el precio con descuento ya viene calculado."""
    return promocion_repo.listar_vigentes(db, hoy)


def promociones_vigentes_por_producto(
    db: Session, claves: Iterable[tuple[int, int, int | None]], hoy: dt.date
) -> dict[int, list[Promocion]]:
    """{producto_id: promociones que le aplican} para varios productos con UNA consulta de
    promociones (no una por producto). `claves` son (producto_id, categoria_id, temporada_id). Una
    promoción aplica si alguno de sus alcances coincide por producto, por categoría o por
    temporada: la misma regla que `listar_vigentes_para` (y por tanto que `calcular_linea`)."""
    vigentes = promocion_repo.listar_vigentes(db, hoy)
    resultado: dict[int, list[Promocion]] = {}
    for producto_id, categoria_id, temporada_id in claves:
        resultado[producto_id] = [
            promocion
            for promocion in vigentes
            if any(
                alcance.producto_id == producto_id
                or alcance.categoria_id == categoria_id
                or (temporada_id is not None and alcance.temporada_id == temporada_id)
                for alcance in promocion.alcances
            )
        ]
    return resultado


# ---- Venta: regla central ----------------------------------------------------------


def registrar_venta(
    db: Session,
    *,
    canal: str,
    sucursal_id: int,
    lineas: list[tuple[int, int]],
    cliente_id: int | None,
    cajero_id: int | None,
    reserva_id: int | None,
    costo_envio: Decimal,
    usuario_id: int | None,
    carrito_a_vaciar: Carrito | None = None,
    commit: bool = True,
    fecha: dt.datetime | None = None,
    precios_pactados: list[tuple[Decimal, Decimal]] | None = None,
) -> Venta:
    """`commit=False`: deja la venta, sus líneas, el stock apartado y el
    vaciado del carrito en flush, sin confirmar; quien llama (la sincronización
    offline, CU-25, o un flujo que además cobra) decide el commit o el
    rollback de todo. Ante un error el llamador debe hacer rollback.

    Solo para la sincronización offline (CU-25), ambos opcionales:
    - `fecha`: la fecha REAL de la venta (UTC naive). Sin ella, la de la base.
    - `precios_pactados`: (precio_unitario, descuento_unitario) de cada línea,
      en el orden de `lineas`. Si vienen, NO se recalcula el precio ni la
      promoción: el cliente pagó ese precio (D17)."""
    if not lineas:
        raise DomainError("La venta necesita al menos una línea")
    if precios_pactados is not None and len(precios_pactados) != len(lineas):
        raise DomainError("precios_pactados debe tener un precio por cada línea")

    plataforma_politicas.obtener_sucursal(db, sucursal_id)
    hoy = hoy_utc()

    if reserva_id is None:
        # Los bloqueos de stock (los que toma reservar_stock más abajo) se
        # adquieren en orden (variante_id, sucursal_id), no en el de las líneas.
        catalogo_politicas.bloquear_stock_en_orden(db, [(variante_id, sucursal_id) for variante_id, _ in lineas])

    # Unidades que la reserva de origen tiene apartadas por variante (las
    # líneas seleccionadas). Si una venta anterior de esa reserva ya liberó o
    # consumió su apartado (se anuló o se pagó), no queda ninguna: lo que haya
    # en cantidad_reservada es de otros.
    unidades_apartadas: dict[int, int] = {}
    if reserva_id is not None:
        if not venta_repo.existe_venta_previa_de_reserva(db, reserva_id):
            for linea_reserva in reserva_repo.obtener(db, reserva_id).detalle:
                if linea_reserva.seleccionada:
                    unidades_apartadas[linea_reserva.variante_id] = (
                        unidades_apartadas.get(linea_reserva.variante_id, 0) + linea_reserva.cantidad
                    )

    # 1. Valida disponibilidad de TODAS las líneas antes de tocar nada.
    variantes: dict[int, ProductoVariante] = {}
    for variante_id, cantidad in lineas:
        variante = catalogo_politicas.obtener_variante(db, variante_id)  # 404 si no existe
        variantes[variante_id] = variante
        if reserva_id is None:
            disponibilidad = _disponibilidad_cu.ejecutar(db, variante_id, sucursal_id)
            disponible = sum(s.cantidad_disponible for s in disponibilidad)
            if cantidad > disponible:
                raise StockInsuficienteError(
                    f"No hay stock disponible suficiente de la variante {variante_id}",
                    variante_id=variante_id,
                    solicitado=cantidad,
                    disponible=max(disponible, 0),
                )
        else:
            # Venta de una reserva (CU-14): esas unidades ya están dentro de
            # cantidad_reservada desde CU-12, no compiten con el disponible
            # (si la reserva se llevó las últimas, el disponible es 0 y
            # compararlo acá impedía cobrarla). Se verifica que el apartado
            # sea el de ESTA reserva: cantidad_reservada es el agregado de
            # toda la variante e incluye unidades de otras reservas y ventas.
            if cantidad > unidades_apartadas.get(variante_id, 0):
                raise ConflictoError(f"La reserva ya no tiene stock apartado de la variante {variante_id}")
            stock = catalogo_politicas.obtener_stock(db, variante_id, sucursal_id)
            if cantidad > stock.cantidad_reservada:
                raise ConflictoError(f"La reserva ya no tiene stock apartado de la variante {variante_id}")

    estado_inicial = estado_venta_repo.obtener_por_codigo(db, "pendiente_pago")
    venta = Venta(
        codigo=generar_codigo(db, "VTA", venta_repo.obtener_por_codigo),
        canal=canal,
        cliente_id=cliente_id,
        sucursal_id=sucursal_id,
        cajero_id=cajero_id,
        reserva_id=reserva_id,
        estado_id=estado_inicial.id,
        costo_envio=costo_envio,
        # Solo si viene: pasar None dejaría el INSERT con NULL en vez del default de la base.
        **({"fecha": fecha} if fecha is not None else {}),
    )
    venta_repo.crear(db, venta)  # flush: venta.id ya disponible

    subtotal_bruto = Decimal("0")
    descuento_total = Decimal("0")

    for posicion, (variante_id, cantidad) in enumerate(lineas):
        variante = variantes[variante_id]
        if precios_pactados is not None:
            precio_unitario, descuento_unitario = precios_pactados[posicion]
            subtotal_linea = redondear((precio_unitario - descuento_unitario) * cantidad)
        else:
            precio_unitario, descuento_unitario, subtotal_linea = calcular_linea(db, variante, cantidad, hoy)

        # 2. costo_unitario queda NULL acá a propósito: recién se congela
        # en confirmar_venta(), cuando el pago se aprueba -- hasta
        # entonces el stock ni siquiera se descontó de verdad, así que no
        # hay un costo "real" de esta salida todavía que congelar.
        db.add(
            VentaDetalle(
                venta_id=venta.id,
                variante_id=variante_id,
                cantidad=cantidad,
                precio_unitario=precio_unitario,
                descuento_unitario=descuento_unitario,
                costo_unitario=None,
                subtotal=subtotal_linea,
            )
        )
        subtotal_bruto += precio_unitario * cantidad
        descuento_total += descuento_unitario * cantidad

        # 3./4. Todavía no se toca físicamente el stock (eso es
        # confirmar_venta): acá solo se RESERVA, para que nadie más se
        # lleve el mismo stock mientras el pago está pendiente. Si la
        # venta viene de una reserva, ese stock ya está reservado desde
        # que se creó la reserva -- reservarlo de nuevo lo dejaría
        # reservado el doble.
        if reserva_id is None:
            catalogo_politicas.reservar_stock(db, variante_id, sucursal_id, cantidad, commit=False)

    # 6. Totales.
    venta.subtotal = redondear(subtotal_bruto)
    venta.descuento = redondear(descuento_total)
    venta.total = redondear(venta.subtotal - venta.descuento + venta.costo_envio)
    if venta.total <= 0:
        # Una venta sin nada que cobrar (promoción del 100 %, precio 0) quedaría pendiente de pago para siempre: la Caja no
        # acepta cobrar 0 y el pago exige un monto mayor a cero. Se rechaza al registrarla, con la causa clara.
        raise DomainError("La venta no tiene nada que cobrar: el total es cero. Revisa los precios y las promociones aplicadas")

    if carrito_a_vaciar is not None:
        carrito_repo.vaciar(db, carrito_a_vaciar)

    confirmar(db, commit)
    db.refresh(venta)
    return venta


# ---- Confirmación / anulación (la dispara Pagos al aprobar/rechazar) ----------------


def _exigir_pendiente_pago(db: Session, venta: Venta) -> None:
    """Solo una venta 'pendiente_pago' se puede confirmar o cobrar. Quien llama
    debe haberla leído con bloqueo (obtener_bloqueado) para que el estado sea
    el vigente."""
    estado_actual = estado_venta_repo.obtener(db, venta.estado_id)
    if estado_actual.codigo != "pendiente_pago":
        raise DomainError(f"No se puede confirmar una venta en estado '{estado_actual.codigo}'")


def confirmar_venta(
    db: Session,
    venta_id: int,
    *,
    usuario_id: int | None = None,
    commit: bool = True,
    avisar_compra: bool = True,
) -> Venta:
    """`avisar_compra`: avisar al comprador de que su compra quedó pagada (notificación y correo, una sola vez por
    venta; ver `_avisar_compra_confirmada`). El pedido sin conexión pasa False: ya tiene su propio aviso.

    Para que la sección de Pagos confirme la venta cuando su pago pasa a 'aprobado'
    (webhook o caja): es recién acá, y no en `registrar_venta`, donde se
    descuenta físicamente el stock y se congela costo_unitario -- hasta
    este momento el stock de la venta solo estaba RESERVADO.

    Bloquea la fila de `venta` (obtener_bloqueado) antes de leer su estado:
    evita que dos llamadas concurrentes (dos webhooks del mismo pago, o un
    webhook y un pago en caja) lean 'pendiente_pago' antes de que ninguna
    comitee y terminen descontando el stock DOS veces para la misma venta."""
    venta = venta_repo.obtener_bloqueado(db, venta_id)
    _exigir_pendiente_pago(db, venta)

    catalogo_politicas.bloquear_stock_en_orden(db, [(linea.variante_id, venta.sucursal_id) for linea in venta.detalle])
    for linea in venta.detalle:
        # Libera la reserva (la haya hecho registrar_venta o la reserva
        # original) antes de descontar, si no actualizar_stock_operacion
        # rechazaría dejar cantidad_reservada sin respaldo físico.
        catalogo_politicas.liberar_stock(db, linea.variante_id, venta.sucursal_id, linea.cantidad, commit=False)

        stock_actual = catalogo_politicas.obtener_stock(db, linea.variante_id, venta.sucursal_id)
        linea.costo_unitario = stock_actual.costo_promedio  # congelado recién ahora

        catalogo_politicas.actualizar_stock_operacion(
            db,
            variante_id=linea.variante_id,
            sucursal_id=venta.sucursal_id,
            tipo_movimiento_codigo="venta",
            cantidad=linea.cantidad,
            referencia_tipo="venta",
            referencia_id=venta.id,
            usuario_id=usuario_id,
            commit=False,
        )

    estado_pagada = estado_venta_repo.obtener_por_codigo(db, "pagada")
    venta.estado_id = estado_pagada.id

    if avisar_compra:
        _avisar_compra_confirmada(db, venta)

    _cerrar_tx(db, venta, commit)
    return venta


def anular_venta(db: Session, venta_id: int, *, commit: bool = True, restaurar_carrito: bool = False) -> Venta:
    """Para que la sección de Pagos anule la venta cuando su pago se rechaza o se
    reembolsa. Se banca los dos casos posibles: si todavía estaba
    'pendiente_pago' (nunca se descontó físicamente), solo libera la
    reserva; si ya estaba 'pagada' (pago aprobado y después reembolsado),
    reingresa el stock como una devolución total, descontando lo que CU-17
    ya había devuelto (cantidad - cantidad devuelta de cada línea).

    `restaurar_carrito`: solo para una venta digital que nunca se pagó
    (rechazada, cancelada por el cliente o vencida) -- registrar_venta
    (canal digital) vació el carrito, así que se le devuelven las prendas
    para que pueda volver a intentarlo sin armarlo de nuevo."""
    venta = venta_repo.obtener_bloqueado(db, venta_id)
    estado_actual = estado_venta_repo.obtener(db, venta.estado_id)

    if estado_actual.codigo == "anulada":
        return venta  # ya estaba anulada: no-op, no un error

    if estado_actual.codigo in ("pendiente_pago", "pagada"):
        catalogo_politicas.bloquear_stock_en_orden(
            db, [(linea.variante_id, venta.sucursal_id) for linea in venta.detalle]
        )

    if estado_actual.codigo == "pendiente_pago":
        for linea in venta.detalle:
            catalogo_politicas.liberar_stock(db, linea.variante_id, venta.sucursal_id, linea.cantidad, commit=False)
        if restaurar_carrito and venta.canal == "digital" and venta.cliente_id is not None:
            _restaurar_carrito(db, venta)
    elif estado_actual.codigo == "pagada":
        for linea in venta.detalle:
            # CU-17 ya reingresó el stock de lo devuelto (y no cambia el estado
            # de la venta): acá solo vuelve lo que sigue fuera del estante.
            # La venta está bloqueada, y RegistrarDevolucion la bloquea antes
            # de registrar, así que esta suma no cambia mientras se anula.
            pendiente = linea.cantidad - devolucion_repo.cantidad_devuelta(db, linea.id)
            if pendiente <= 0:
                continue
            catalogo_politicas.actualizar_stock_operacion(
                db,
                variante_id=linea.variante_id,
                sucursal_id=venta.sucursal_id,
                tipo_movimiento_codigo="devolucion",
                cantidad=pendiente,
                referencia_tipo="venta_anulada",
                referencia_id=venta.id,
                commit=False,
            )
    else:
        raise DomainError(f"No se puede anular una venta en estado '{estado_actual.codigo}'")

    estado_anulada = estado_venta_repo.obtener_por_codigo(db, "anulada")
    venta.estado_id = estado_anulada.id

    _cerrar_tx(db, venta, commit)
    return venta


def marcar_venta_entregada(db: Session, venta_id: int, *, commit: bool = True) -> Venta:
    """Para que la sección de Entregas (CU-19) cierre la venta cuando su envío llega a
    'entregado'. Solo una venta 'pagada' puede entregarse; si ya estaba
    'entregada' no hace nada (reintento inofensivo). Bloquea la fila igual
    que confirmar_venta/anular_venta para serializar con ellas."""
    venta = venta_repo.obtener_bloqueado(db, venta_id)
    estado_actual = estado_venta_repo.obtener(db, venta.estado_id)
    if estado_actual.codigo == "entregada":
        return venta
    if estado_actual.codigo != "pagada":
        raise DomainError(f"No se puede entregar una venta en estado '{estado_actual.codigo}'")

    estado_entregada = estado_venta_repo.obtener_por_codigo(db, "entregada")
    venta.estado_id = estado_entregada.id

    _cerrar_tx(db, venta, commit)
    return venta


def _restaurar_carrito(db: Session, venta: Venta) -> None:
    carrito = carrito_repo.obtener_o_crear(db, venta.cliente_id)
    for linea_venta in venta.detalle:
        linea = carrito_repo.obtener_linea(db, carrito.id, linea_venta.variante_id)
        if linea is None:
            db.add(CarritoDetalle(carrito_id=carrito.id, variante_id=linea_venta.variante_id, cantidad=linea_venta.cantidad))
        else:
            # Si el cliente ya la volvió a agregar a mano, no se duplica.
            linea.cantidad = max(linea.cantidad, linea_venta.cantidad)
    db.flush()


def es_venta_pendiente(db: Session, venta_id: int) -> bool:
    """Para que la sección de Pagos sepa si una venta todavía espera su pago."""
    venta = venta_repo.obtener(db, venta_id)
    return estado_venta_repo.obtener(db, venta.estado_id).codigo == "pendiente_pago"


def listar_ventas_pendientes_vencidas(db: Session, minutos: int) -> list[int]:
    """Para la sección de Pagos (expiración de ventas pendientes): ids de ventas que
    siguen en 'pendiente_pago' desde hace más de `minutos`. `venta.fecha`
    se guarda sin zona horaria con el now() de la base (UTC en Railway y en
    SQLite)."""
    limite = ahora_utc_naive() - dt.timedelta(minutes=minutos)
    estado = estado_venta_repo.obtener_por_codigo(db, "pendiente_pago")
    return list(
        db.scalars(select(Venta.id).where(Venta.estado_id == estado.id, Venta.fecha < limite).order_by(Venta.id))
    )


def subconsulta_ventas_de_sucursal(sucursal_id: int) -> Select[tuple[int]]:
    """Para que la sección de Entregas (CU-19) filtre sus envíos por sucursal con
    `Envio.venta_id.in_(...)` sin nombrar la tabla `venta`: la consulta se
    arma acá, en la sección dueña de esa tabla."""
    return select(Venta.id).where(Venta.sucursal_id == sucursal_id)


def obtener_venta(db: Session, venta_id: int) -> Venta:
    """Para que la sección de Pagos lea una venta (monto, sucursal, etc.) sin
    consultar `venta` directamente."""
    return venta_repo.obtener(db, venta_id)


def obtener_venta_bloqueada(db: Session, venta_id: int) -> Venta:
    """Para que la sección de Pagos (al iniciar un pago por pasarela) bloquee la venta
    antes de validar que no haya ya un pago activo: serializa esa
    validación con cualquier confirmar_venta/anular_venta concurrente
    sobre la misma venta, sin que Pagos tenga que consultar `venta`
    directamente."""
    return venta_repo.obtener_bloqueado(db, venta_id)


def mapa_codigos_estado_venta(db: Session) -> dict[int, str]:
    """Para que el router arme VentaRespuesta sin consultar `estado_venta`
    directamente."""
    return estado_venta_repo.mapa_codigos_por_id(db)


def obtener_estado_codigo(db: Session, estado_id: int) -> str:
    """Para que la sección de Pagos traduzca el `estado_id` de una venta a su código
    ('pendiente_pago', 'pagada', ...) sin consultar `estado_venta`
    directamente."""
    return estado_venta_repo.obtener(db, estado_id).codigo


def obtener_comprobante(db: Session, venta_id: int, usuario_id: int) -> Venta:
    """Valida que quien pide el comprobante sea el dueño de la venta o
    personal de sucursal, y lo devuelve. La usa CU-15 directamente, y
    también las secciones de Pagos (CU-18) y Entregas (CU-19) como chequeo de
    acceso antes de operar sobre la venta: no se duplica la regla en cada
    sección. El personal solo accede a las ventas de su propia sucursal."""
    venta = venta_repo.obtener(db, venta_id)
    if PERMISO_STAFF_VENTAS in permisos_de_usuario(db, usuario_id):
        plataforma_politicas.validar_acceso_sucursal(db, usuario_id, venta.sucursal_id)
    else:
        cliente = obtener_perfil_cliente(db, usuario_id)
        if cliente is None or venta.cliente_id != cliente.id:
            raise PermisoDenegadoError("No tenés acceso a esta venta")
    return venta


# ---- Plazo para devolver o cambiar prendas (D19) ---------------------------------------


def _duracion_legible(transcurrido: dt.timedelta) -> str:
    """'26 h 10 min'; desde las 48 h, '2 días 3 h'."""
    minutos = int(transcurrido.total_seconds() // 60)
    horas, minutos_sueltos = divmod(minutos, 60)
    if horas < 48:
        return f"{horas} h {minutos_sueltos} min"
    dias, horas_sueltas = divmod(horas, 24)
    return f"{dias} días {horas_sueltas} h"


def _plazo_legible(plazo_horas: int) -> str:
    return "1 hora" if plazo_horas == 1 else f"{plazo_horas} horas"


def validar_plazo_cambio(
    fecha_venta: dt.datetime, plazo_horas: int, ahora: dt.datetime, tolerancia_horas: int = 0
) -> None:
    """Pura: 409 si `ahora` pasó `fecha_venta + plazo_horas (+ tolerancia_horas)`. El límite es
    inclusivo (a las 24:00:00 exactas aún se acepta; a las 24:00:01 no). La tolerancia solo se usa al ATENDER una
    solicitud que el cliente hizo dentro del plazo (el cliente puede llegar a la tienda unas horas después)."""
    if ahora > fecha_venta + dt.timedelta(hours=plazo_horas + tolerancia_horas):
        extra = ""
        if tolerancia_horas:
            extra = f" (más {_plazo_legible(tolerancia_horas)} de tolerancia para atender la solicitud)"
        raise PlazoCambioVencidoError(
            "El plazo para cambiar prendas de esta venta ya venció: se hizo hace "
            f"{_duracion_legible(ahora - fecha_venta)} y el plazo es de {_plazo_legible(plazo_horas)}{extra}."
        )


def exigir_plazo_cambio(
    db: Session, venta: Venta, ahora: dt.datetime | None = None, tolerancia_horas: int = 0
) -> None:
    """Aplica el plazo de la empresa de la sesión a la venta. Se cuenta desde
    `Venta.fecha`, que en una venta offline es la fecha de la operación y no la
    de la sincronización."""
    validar_plazo_cambio(
        venta.fecha,
        plataforma_politicas.obtener_plazo_cambio_horas(db),
        ahora or ahora_utc_naive(),
        tolerancia_horas,
    )


def describir_plazo_cambio(db: Session, venta: Venta) -> dict:
    """Para `GET /ventas/{id}/plazo-cambio`: fecha, plazo, vencimiento y si sigue vigente."""
    plazo_horas = plataforma_politicas.obtener_plazo_cambio_horas(db)
    vence_en = venta.fecha + dt.timedelta(hours=plazo_horas)
    return {
        "venta_id": venta.id,
        "fecha_venta": venta.fecha,
        "plazo_horas": plazo_horas,
        "vence_en": vence_en,
        "vigente": ahora_utc_naive() <= vence_en,
        "estado_venta": obtener_estado_codigo(db, venta.estado_id),
    }


# ---- Cambio de talla o color y comprobante por correo (CU-17) ----


def unidades_devueltas_por_venta(db: Session, ventas: Iterable[Venta]) -> dict[int, int]:
    """Para las listas de ventas: cuántas unidades se devolvieron de cada una (`venta_id` -> unidades; sin
    devoluciones no aparece). La devolución NO cambia el estado de la venta (puede ser parcial y los reportes cuentan
    solo `pagada` y `entregada`): este dato se calcula aparte para que las pantallas lo muestren."""
    return devolucion_repo.unidades_devueltas_por_venta(db, [v.id for v in ventas])


def devuelto_por_venta_y_linea(db: Session, ventas: Iterable[Venta]) -> tuple[dict[int, int], dict[int, int]]:
    """Lo devuelto de las ventas de una respuesta, en UNA consulta: (`venta_id` -> unidades, `venta_detalle_id` ->
    unidades). Lo segundo permite que cada línea diga `cantidad_devuelta` y que las pantallas no ofrezcan cambiar lo
    que ya se devolvió."""
    return devolucion_repo.devuelto_por_venta_y_linea(db, [v.id for v in ventas])


def validar_cambio_de_variante(original, nueva) -> None:
    """Un cambio entrega OTRA variante del MISMO producto y del MISMO precio: así no hay diferencia de dinero que
    cobrar ni devolver (el reembolso todavía no existe). `original` y `nueva` son `ProductoVariante`."""
    if nueva.id == original.id:
        raise DomainError("La prenda nueva es la misma que se devuelve: elige otra talla o color")
    if nueva.producto_id != original.producto_id:
        raise DomainError("El cambio es de talla o color de la misma prenda: la nueva debe ser del mismo producto")
    if not nueva.activo:
        raise DomainError("La talla o el color elegido ya no se vende")
    if catalogo_politicas.obtener_precio_efectivo(nueva) != catalogo_politicas.obtener_precio_efectivo(original):
        raise DomainError("El cambio tiene diferencia de precio: todavía no se puede registrar")


def comprador_de_venta(db: Session, venta: Venta) -> tuple[int, str, str] | None:
    """(usuario_id, correo, nombre) de quien compró, o None si la venta no tiene cliente (p. ej. una venta presencial
    sin cuenta) o su usuario está inactivo o sin correo."""
    if venta.cliente_id is None:
        return None
    cliente = plataforma_politicas.obtener_cliente(db, venta.cliente_id)
    usuario = plataforma_politicas.obtener_usuario(db, cliente.usuario_id)
    if not usuario.activo or not usuario.email:
        return None
    return usuario.id, usuario.email, usuario.nombre


def destinatario_de_venta(db: Session, venta: Venta) -> tuple[str, str] | None:
    """(correo, nombre) de quien compró, o None si la venta no tiene cliente (p. ej. una venta presencial sin
    cuenta) o su usuario está inactivo."""
    comprador = comprador_de_venta(db, venta)
    return None if comprador is None else (comprador[1], comprador[2])


def _fecha_legible(fecha: dt.datetime) -> str:
    """La fecha en hora de Bolivia. Las fechas de la base son UTC sin zona."""
    con_zona = fecha.replace(tzinfo=dt.timezone.utc) if fecha.tzinfo is None else fecha
    return con_zona.astimezone(ZONA_BOLIVIA).strftime("%d/%m/%Y %H:%M")


def construir_correo_comprobante_devolucion(
    *,
    para_email: str,
    nombre: str,
    nombre_empresa: str,
    codigo_devolucion: str,
    codigo_venta: str,
    sucursal: str,
    fecha: dt.datetime,
    lineas: list[tuple[str, str | None, int]],
) -> MensajeCorreo:
    """El comprobante de una devolución (sin reposición) o de un cambio de talla o color. `lineas` son
    (prenda devuelta, prenda entregada en su lugar o None, cantidad). Todo dato variable se escapa en el HTML."""
    es_cambio = any(nueva is not None for _, nueva, _ in lineas)
    titulo = "Comprobante de cambio" if es_cambio else "Comprobante de devolución"
    asunto = f"{titulo} {codigo_devolucion} · {nombre_empresa}"
    cuando = _fecha_legible(fecha)

    filas_texto: list[str] = []
    filas_html: list[str] = []
    for devuelta, nueva, cantidad in lineas:
        if nueva is None:
            filas_texto.append(f"- Devolviste: {devuelta} (x{cantidad})")
            filas_html.append(
                f'<li style="margin:0 0 8px">Devolviste: <strong>{escape(devuelta)}</strong> (x{cantidad})</li>'
            )
        else:
            filas_texto.append(f"- Devolviste: {devuelta} (x{cantidad})\n  Recibes en su lugar: {nueva} (x{cantidad})")
            filas_html.append(
                f'<li style="margin:0 0 8px">Devolviste: <strong>{escape(devuelta)}</strong> (x{cantidad})<br>'
                f"Recibes en su lugar: <strong>{escape(nueva)}</strong> (x{cantidad})</li>"
            )

    texto = (
        f"Hola {nombre},\n\n"
        f"{titulo} {codigo_devolucion} de tu compra {codigo_venta} en {nombre_empresa}.\n"
        f"Sucursal: {sucursal}\nFecha: {cuando}\n\n" + "\n".join(filas_texto) + "\n\n"
        "Guarda este mensaje como constancia. Si no reconoces esta operación, responde a la tienda.\n"
    )
    html = (
        '<!doctype html><html lang="es"><body style="margin:0;background:#F7F5F1;font-family:Arial,Helvetica,sans-serif;'
        'color:#161412"><div style="max-width:480px;margin:0 auto;padding:24px">'
        '<p style="font-size:13px;letter-spacing:1px;text-transform:uppercase;color:#6B645C;margin:0 0 16px">'
        f"{escape(nombre_empresa)}</p>"
        f'<h1 style="font-size:22px;margin:0 0 12px">{escape(titulo)}</h1>'
        f'<p style="font-size:15px;line-height:1.5">Hola {escape(nombre)}, registramos la operación '
        f"<strong>{escape(codigo_devolucion)}</strong> sobre tu compra <strong>{escape(codigo_venta)}</strong>.</p>"
        f'<p style="font-size:14px;color:#6B645C;margin:0 0 12px">Sucursal: {escape(sucursal)}<br>Fecha: {escape(cuando)}</p>'
        f'<ul style="font-size:15px;line-height:1.5;padding-left:18px;margin:0 0 16px">{"".join(filas_html)}</ul>'
        '<p style="font-size:13px;line-height:1.5;color:#6B645C">Guarda este mensaje como constancia. Si no reconoces '
        "esta operación, responde a la tienda.</p></div></body></html>"
    )
    return MensajeCorreo(para_email=para_email, para_nombre=nombre, asunto=asunto, html=html, texto=texto)


# ---- Solicitud de cambio de talla o color del cliente (Etapa 2 de CU-17) -------------------


def atender_solicitud_hasta(db: Session, venta: Venta) -> dt.datetime:
    """Hasta cuándo se puede aprobar una solicitud de esa venta: fin del plazo de cambio más la tolerancia. Pasado
    ese instante la solicitud pendiente vence sola."""
    horas = plataforma_politicas.obtener_plazo_cambio_horas(db) + get_settings().solicitud_cambio_tolerancia_horas
    return venta.fecha + dt.timedelta(hours=horas)


def _nombre_del_comprador(db: Session, venta: Venta) -> str | None:
    if venta.cliente_id is None:
        return None
    cliente = plataforma_politicas.obtener_cliente(db, venta.cliente_id)
    usuario = plataforma_politicas.obtener_usuario(db, cliente.usuario_id)
    return f"{usuario.nombre} {usuario.apellido}".strip()


def _disponible_en_sucursal(db: Session, variante_id: int, sucursal_id: int) -> int:
    try:
        return int(catalogo_politicas.obtener_stock(db, variante_id, sucursal_id).cantidad_disponible)
    except NoEncontradoError:
        return 0


def construir_respuesta_solicitud(
    db: Session,
    devolucion: Devolucion,
    venta: Venta,
    correo_programado: bool = False,
    reembolsos: list[Reembolso] | None = None,
) -> SolicitudCambioRespuesta:
    """La solicitud con lo que las pantallas necesitan: las prendas con su nombre y, mientras esté pendiente, cuánto
    hay hoy de la prenda nueva en la sucursal (informativo; no se reserva). `reembolsos`: el dinero devuelto al aprobarla
    (si se omite, se leen los de esta devolución, que es lo que necesita una solicitud ya resuelta)."""
    lineas_venta = {linea.id: linea for linea in venta.detalle}
    pendiente = devolucion.estado == "pendiente"
    detalle = []
    for linea in devolucion.detalle:
        original = catalogo_politicas.obtener_variante_aunque_este_dada_de_baja(
            db, lineas_venta[linea.venta_detalle_id].variante_id
        )
        nueva = (
            catalogo_politicas.obtener_variante(db, linea.variante_nueva_id)
            if linea.variante_nueva_id is not None
            else None
        )
        detalle.append(
            SolicitudCambioLineaRespuesta(
                venta_detalle_id=linea.venta_detalle_id,
                cantidad=linea.cantidad,
                variante_devuelta_id=original.id,
                prenda_devuelta=catalogo_politicas.describir_variante(db, original),
                variante_nueva_id=linea.variante_nueva_id,
                prenda_nueva=catalogo_politicas.describir_variante(db, nueva) if nueva is not None else None,
                disponible_nueva=(
                    _disponible_en_sucursal(db, nueva.id, venta.sucursal_id) if pendiente and nueva is not None else None
                ),
            )
        )
    return SolicitudCambioRespuesta(
        id=devolucion.id,
        codigo=devolucion.codigo,
        venta_id=venta.id,
        venta_codigo=venta.codigo,
        sucursal_id=venta.sucursal_id,
        cliente_nombre=_nombre_del_comprador(db, venta),
        fecha=devolucion.fecha,
        estado=devolucion.estado,
        motivo=devolucion.motivo,
        motivo_rechazo=devolucion.motivo_rechazo,
        resuelta_en=devolucion.resuelta_en,
        atender_hasta=atender_solicitud_hasta(db, venta),
        detalle=detalle,
        reembolsos=[
            ReembolsoRespuesta.model_validate(fila)
            for fila in (reembolsos if reembolsos is not None else _reembolsos_de_devolucion(db, devolucion))
        ],
        correo_programado=correo_programado,
    )


def _reembolsos_de_devolucion(db: Session, devolucion: Devolucion) -> list[Reembolso]:
    """Los reembolsos que dejó esa devolución (solo una aprobada los tiene)."""
    if devolucion.estado != "aprobada":
        return []
    return [fila for fila in reembolso_repo.listar_por_venta(db, devolucion.venta_id) if fila.devolucion_id == devolucion.id]


def _correo_de_solicitud(
    *,
    para_email: str,
    nombre: str,
    nombre_empresa: str,
    asunto: str,
    titulo: str,
    intro: str,
    lineas: list[str],
    cierre: str,
) -> MensajeCorreo:
    """Cuerpo común de los correos de una solicitud. Todo dato variable se escapa en el HTML."""
    texto = f"Hola {nombre},\n\n{intro}\n\n" + "\n".join(f"- {linea}" for linea in lineas) + f"\n\n{cierre}\n"
    items = "".join(f'<li style="margin:0 0 8px">{escape(linea)}</li>' for linea in lineas)
    html = (
        '<!doctype html><html lang="es"><body style="margin:0;background:#F7F5F1;font-family:Arial,Helvetica,sans-serif;'
        'color:#161412"><div style="max-width:480px;margin:0 auto;padding:24px">'
        '<p style="font-size:13px;letter-spacing:1px;text-transform:uppercase;color:#6B645C;margin:0 0 16px">'
        f"{escape(nombre_empresa)}</p>"
        f'<h1 style="font-size:22px;margin:0 0 12px">{escape(titulo)}</h1>'
        f'<p style="font-size:15px;line-height:1.5">Hola {escape(nombre)}, {escape(intro)}</p>'
        f'<ul style="font-size:15px;line-height:1.5;padding-left:18px;margin:0 0 16px">{items}</ul>'
        f'<p style="font-size:13px;line-height:1.5;color:#6B645C">{escape(cierre)}</p></div></body></html>'
    )
    return MensajeCorreo(para_email=para_email, para_nombre=nombre, asunto=asunto, html=html, texto=texto)


def construir_correo_solicitud_recibida(
    *,
    para_email: str,
    nombre: str,
    nombre_empresa: str,
    codigo_solicitud: str,
    codigo_venta: str,
    sucursal: str,
    atender_hasta: dt.datetime,
    lineas: list[tuple[str, str | None, int]],
) -> MensajeCorreo:
    """Aviso de que la solicitud quedó registrada y adónde llevar la prenda. `lineas`: (prenda que devuelve, prenda
    que quiere o `None` si pide que le devuelvan su dinero, cantidad). Si NINGUNA línea pide cambio es una solicitud de
    devolución con reembolso y el texto lo dice."""
    solo_devolucion = all(nueva is None for _devuelta, nueva, _cantidad in lineas)
    if solo_devolucion:
        asunto = f"Recibimos tu solicitud de devolución {codigo_solicitud} · {nombre_empresa}"
        titulo = "Recibimos tu solicitud de devolución"
        intro = (
            f"registramos tu solicitud {codigo_solicitud} sobre tu compra {codigo_venta}. "
            f"Lleva la prenda a la sucursal {sucursal} hasta el {_fecha_legible(atender_hasta)}: allí la revisan y, "
            "si todo está en orden, te devolvemos tu dinero."
        )
        cierre = (
            "El reembolso se hace cuando la tienda revisa la prenda que llevas, y te avisaremos cuando salga. "
            "Si ya no quieres devolverla, cancela la solicitud desde tu compra."
        )
    else:
        asunto = f"Recibimos tu solicitud de cambio {codigo_solicitud} · {nombre_empresa}"
        titulo = "Recibimos tu solicitud de cambio"
        intro = (
            f"registramos tu solicitud {codigo_solicitud} sobre tu compra {codigo_venta}. "
            f"Lleva la prenda a la sucursal {sucursal} hasta el {_fecha_legible(atender_hasta)}: allí la revisan y, "
            "si hay stock de lo que pides, te la cambian."
        )
        cierre = (
            "Todavía no reservamos la prenda nueva: se confirma cuando la tienda revisa la prenda que llevas. "
            "Si ya no quieres el cambio, cancélalo desde tu compra."
        )
    return _correo_de_solicitud(
        para_email=para_email,
        nombre=nombre,
        nombre_empresa=nombre_empresa,
        asunto=asunto,
        titulo=titulo,
        intro=intro,
        lineas=[
            f"Devuelves: {devuelta} (x{cantidad}) · "
            + (f"Quieres: {nueva}" if nueva is not None else "Quieres: que te devolvamos tu dinero")
            for devuelta, nueva, cantidad in lineas
        ],
        cierre=cierre,
    )


def construir_correo_solicitud_rechazada(
    *,
    para_email: str,
    nombre: str,
    nombre_empresa: str,
    codigo_solicitud: str,
    codigo_venta: str,
    motivo: str,
) -> MensajeCorreo:
    return _correo_de_solicitud(
        para_email=para_email,
        nombre=nombre,
        nombre_empresa=nombre_empresa,
        asunto=f"Tu solicitud de cambio {codigo_solicitud} no fue aprobada · {nombre_empresa}",
        titulo="Tu solicitud de cambio no fue aprobada",
        intro=f"revisamos tu solicitud {codigo_solicitud} sobre la compra {codigo_venta} y no pudimos aprobarla.",
        lineas=[f"Motivo: {motivo}"],
        cierre="Si tienes dudas, responde a la tienda o acércate a la sucursal de tu compra.",
    )


def vencer_solicitudes_cambio(db: Session) -> int:
    """Pasa a 'vencida' las solicitudes pendientes de la empresa de la sesión que ya pasaron su `atender_hasta`
    (nadie las atendió a tiempo). Cada una se bloquea y se vuelve a mirar antes de tocarla: si un cajero la aprobó
    justo ahora, no se pisa. Devuelve cuántas venció."""
    ahora = ahora_utc_naive()
    vencidas = 0
    for devolucion, venta in devolucion_repo.listar_pendientes_con_venta(db):
        if ahora <= atender_solicitud_hasta(db, venta):
            continue
        bloqueada = devolucion_repo.obtener_bloqueado(db, devolucion.id)
        if bloqueada.estado != "pendiente":
            db.rollback()
            continue
        bloqueada.estado = "vencida"
        bloqueada.resuelta_en = ahora
        db.commit()
        vencidas += 1
    return vencidas


def vencer_solicitudes_de_todas_las_empresas(db: Session) -> int:
    """`vencer_solicitudes_cambio` una vez por cada empresa activa (tarea periódica, sin actor humano). Una empresa
    que falla no frena a las demás."""
    resultados = por_cada_empresa(db, plataforma_politicas.listar_empresas_activas(db), vencer_solicitudes_cambio)
    return sum(r or 0 for r in resultados)


# ---- Puntos de entrada para `inteligencia` (reportes y recomendador) ----------


def listar_variantes_compradas(db: Session, cliente_id: int) -> set[int]:
    """Para `inteligencia` (capa de reglas del recomendador): variantes que
    un cliente ya compró, para excluirlas del recomendador. Cuenta
    cualquier venta que no haya sido anulada (pendiente_pago/pagada/
    entregada sí cuentan)."""
    filas = db.scalars(
        select(VentaDetalle.variante_id)
        .join(Venta, Venta.id == VentaDetalle.venta_id)
        .join(EstadoVenta, EstadoVenta.id == Venta.estado_id)
        .where(Venta.cliente_id == cliente_id, EstadoVenta.codigo != "anulada")
        .distinct()
    )
    return set(filas)


def reporte_ventas_detalle(
    db: Session,
    periodo: ParametrosPeriodo,
    sucursal_id: int | None = None,
    categoria_id: int | None = None,
    canal: str | None = None,
) -> list[dict]:
    """Para `inteligencia` (reportes): filas crudas de vw_ventas_detalle."""
    return comercial_repo.detalle(db, periodo.desde, periodo.hasta, sucursal_id, categoria_id, canal)


def reporte_ventas_resumen(
    db: Session,
    periodo: ParametrosPeriodo,
    sucursal_id: int | None = None,
    categoria_id: int | None = None,
    canal: str | None = None,
    *,
    sucursal_ids: list[int] | None = None,
    categoria_ids: list[int] | None = None,
) -> dict:
    """Para `inteligencia` (reportes): total vendido, transacciones y margen bruto del
    período (el ticket promedio lo calcula quien llama, dividiendo). Los parámetros en lista
    (reportes generativos) se suman a los singulares; una lista vacía no coincide con nada."""
    return comercial_repo.resumen(
        db,
        periodo.desde,
        periodo.hasta,
        sucursal_id,
        categoria_id,
        canal,
        sucursal_ids=sucursal_ids,
        categoria_ids=categoria_ids,
    )


def reporte_ventas_top_productos(
    db: Session,
    periodo: ParametrosPeriodo,
    sucursal_id: int | None = None,
    categoria_id: int | None = None,
    canal: str | None = None,
    limite: int = 10,
    *,
    sucursal_ids: list[int] | None = None,
    categoria_ids: list[int] | None = None,
    producto_ids: list[int] | None = None,
    ascendente: bool = False,
) -> list[dict]:
    """Para `inteligencia` (reportes): productos más vendidos del período; con `ascendente`,
    los menos vendidos (solo entre los que tuvieron ventas). Los filtros en lista (reportes
    generativos) se suman a los singulares; una lista vacía no coincide con nada."""
    return comercial_repo.top_productos(
        db,
        periodo.desde,
        periodo.hasta,
        sucursal_id,
        categoria_id,
        canal,
        limite,
        sucursal_ids=sucursal_ids,
        categoria_ids=categoria_ids,
        producto_ids=producto_ids,
        ascendente=ascendente,
    )


def reporte_ventas_por_canal(
    db: Session, periodo: ParametrosPeriodo, sucursal_id: int | None = None, categoria_id: int | None = None
) -> list[dict]:
    """Para `inteligencia` (reportes): ventas agrupadas por canal (digital/presencial)."""
    return comercial_repo.por_canal(db, periodo.desde, periodo.hasta, sucursal_id, categoria_id)


def reporte_ventas_por_sucursal(
    db: Session,
    periodo: ParametrosPeriodo,
    categoria_id: int | None = None,
    canal: str | None = None,
    sucursal_id: int | None = None,
    *,
    sucursal_ids: list[int] | None = None,
    categoria_ids: list[int] | None = None,
) -> list[dict]:
    """Para `inteligencia` (reportes): ventas agrupadas por sucursal (con `sucursal_id`,
    solo la fila de esa sucursal: lo que ve un encargado). Los filtros en lista (reportes
    generativos) se suman a los singulares; una lista vacía no coincide con nada."""
    return comercial_repo.por_sucursal(
        db,
        periodo.desde,
        periodo.hasta,
        categoria_id,
        canal,
        sucursal_id,
        sucursal_ids=sucursal_ids,
        categoria_ids=categoria_ids,
    )


_DESGLOSES_SERIE = ("sucursal", "categoria")
_DOS_DECIMALES = Decimal("0.01")


def _dinero(valor) -> Decimal:
    """Un total de la base como Decimal con 2 decimales. SQLite (solo las pruebas) devuelve
    float en SUM(); PostgreSQL, Decimal: `Decimal(str(x))` sirve para ambos."""
    return Decimal(str(valor if valor is not None else 0)).quantize(_DOS_DECIMALES, rounding=ROUND_HALF_UP)


def resumen_ventas_del_dia(
    db: Session, desde: dt.datetime, hasta: dt.datetime, sucursal_id: int | None, *, mas_vendidas: int = 4, recientes: int = 5
) -> dict:
    """Para `inteligencia` (pantalla de inicio del personal): lo vendido en [desde, hasta) (instantes UTC) de una
    sucursal o de todas, calculado en la base sin traer el historial. Devuelve `tickets` y `total` (pagadas y
    entregadas), `por_cobrar_cantidad` y `por_cobrar_total` (pendientes de pago), `mas_vendidas`
    (`[(variante_id, unidades)]`) y `recientes` (las últimas ventas del día, de cualquier estado, con lo devuelto).
    Solo las pagadas y entregadas cuentan como "vendido": una pendiente de pago aún puede cancelarse."""
    por_estado = venta_repo.totales_del_dia_por_estado(db, desde, hasta, sucursal_id)
    vendidas = [por_estado[codigo] for codigo in ESTADOS_COMPRA_PAGADA if codigo in por_estado]
    cobrar_cantidad, cobrar_total = por_estado.get("pendiente_pago", (0, 0))

    ventas = venta_repo.recientes_del_dia(db, desde, hasta, sucursal_id, recientes)
    estados = mapa_codigos_estado_venta(db)
    devuelto_por_venta, _ = devuelto_por_venta_y_linea(db, ventas)
    return {
        "tickets": sum(cantidad for cantidad, _total in vendidas),
        "total": _dinero(sum((_dinero(total) for _cantidad, total in vendidas), Decimal(0))),
        "por_cobrar_cantidad": cobrar_cantidad,
        "por_cobrar_total": _dinero(cobrar_total),
        "mas_vendidas": venta_repo.unidades_vendidas_del_dia_por_variante(
            db, desde, hasta, sucursal_id, ESTADOS_COMPRA_PAGADA, mas_vendidas
        ),
        "recientes": [
            {
                "id": v.id,
                "codigo": v.codigo,
                "fecha": v.fecha,
                "total": v.total,
                "estado": estados[v.estado_id],
                "unidades_vendidas": sum(d.cantidad for d in v.detalle),
                "unidades_devueltas": devuelto_por_venta.get(v.id, 0),
            }
            for v in ventas
        ],
    }


def reporte_ventas_serie_diaria(
    db: Session,
    periodo: ParametrosPeriodo,
    *,
    sucursal_ids: list[int] | None = None,
    categoria_ids: list[int] | None = None,
    producto_ids: list[int] | None = None,
    canal: str | None = None,
    desglose: tuple[str, ...] = (),
) -> list[dict]:
    """Para `inteligencia` (reportes generativos): ventas por día del período (solo los días
    con ventas), por orden de fecha. `desglose` admite "sucursal" y/o "categoria" (otro valor
    es un error: 400). Cada fila trae `dia` (date), [`sucursal_id`, `sucursal`],
    [`categoria_id`, `categoria`], `transacciones` (ventas distintas), `unidades` y
    `total_ventas` (Decimal de 2 decimales). El filtro por productos solo restringe: no hay
    desglose por producto. Cuenta solo ventas pagadas o entregadas."""
    invalidos = [valor for valor in desglose if valor not in _DESGLOSES_SERIE]
    if invalidos:
        raise DomainError(f"Desglose no soportado: {', '.join(invalidos)}. Usa sucursal o categoria.")
    filas = comercial_repo.serie_diaria(
        db,
        periodo.desde,
        periodo.hasta,
        sucursal_ids=sucursal_ids,
        categoria_ids=categoria_ids,
        producto_ids=producto_ids,
        canal=canal,
        desglose=tuple(desglose),
    )
    return [
        {
            **fila,
            "dia": dt.date.fromisoformat(str(fila["dia"])[:10]),
            "transacciones": int(fila["transacciones"]),
            "unidades": int(fila["unidades"]),
            "total_ventas": _dinero(fila["total_ventas"]),
            "ventas_brutas": _dinero(fila["ventas_brutas"]),
        }
        for fila in filas
    ]


# Tope por defecto de clientes del RFM. Es el mismo número que `ML_MAX_CLIENTES` de
# `inteligencia.ml.limites`, pero `comercial` no puede importar `inteligencia` (el orden de
# dependencias es core <- plataforma <- catalogo <- comercial <- inteligencia): quien llama
# desde `inteligencia` pasa su propio límite.
_TOPE_CLIENTES_RFM = 50_000


def reporte_rfm_clientes(
    db: Session, hasta: dt.date, dias: int = 365, tope: int = _TOPE_CLIENTES_RFM
) -> list[dict]:
    """Para `inteligencia` (segmentación de clientes, E11): una fila por cliente con compras
    efectivas (pagada o entregada) en la ventana `(hasta - dias, hasta]`, es decir, los `dias`
    días que terminan en `hasta` inclusive. Cada fila: `cliente_id`, `ultima_compra` (date),
    `frecuencia` (ventas efectivas, int) y `monto_total` (Decimal de 2 decimales, suma del
    total de esas ventas). Las ventas anónimas no entran. Orden por `cliente_id` y como máximo
    `tope` filas. No trae nombres ni correos: el modelo no debe verlos."""
    if dias < 1:
        raise DomainError("La ventana del RFM debe tener al menos 1 día.")
    if tope < 1:
        raise DomainError("El tope de clientes del RFM debe ser al menos 1.")
    desde = hasta - dt.timedelta(days=dias - 1)  # (hasta - dias, hasta] == [hasta - dias + 1, hasta]
    filas = comercial_repo.rfm_clientes(db, desde, hasta, tope)
    return [
        {
            "cliente_id": int(fila["cliente_id"]),
            "ultima_compra": fila["ultima_compra"].date()
            if isinstance(fila["ultima_compra"], dt.datetime)
            else dt.date.fromisoformat(str(fila["ultima_compra"])[:10]),
            "frecuencia": int(fila["frecuencia"]),
            "monto_total": _dinero(fila["monto_total"]),
        }
        for fila in filas
    ]


def reporte_ventas_por_categoria(
    db: Session,
    periodo: ParametrosPeriodo,
    *,
    sucursal_ids: list[int] | None = None,
    canal: str | None = None,
) -> list[dict]:
    """Para `inteligencia` (reportes generativos): ventas del período por categoría, de la que
    más vendió a la que menos. Cada fila: `categoria_id`, `categoria`, `unidades`,
    `total_vendido` y `margen_bruto` (Decimal de 2 decimales), `transacciones`. La categoría es
    la del producto (sin subcategorías). Cuenta solo ventas pagadas o entregadas."""
    filas = comercial_repo.por_categoria(
        db, periodo.desde, periodo.hasta, sucursal_ids=sucursal_ids, canal=canal
    )
    return [
        {
            **fila,
            "unidades": int(fila["unidades"]),
            "total_vendido": _dinero(fila["total_vendido"]),
            "margen_bruto": _dinero(fila["margen_bruto"]),
            "transacciones": int(fila["transacciones"]),
        }
        for fila in filas
    ]


def contar_ventas_con_reserva(db: Session, periodo: ParametrosPeriodo, sucursal_id: int | None = None) -> int:
    """Para `inteligencia` (reportes, tasa de conversión de reservas a ventas): ventas
    del período que se originaron en una reserva."""
    return comercial_repo.contar_ventas_con_reserva(db, periodo.desde, periodo.hasta, sucursal_id)


def contar_ventas_por_variante(db: Session, variante_ids: list[int]) -> dict[int, int]:
    """Para `inteligencia` (fallback de popularidad para clientes nuevos/
    anónimos sin historial): cantidad total vendida de cada variante,
    contando solo ventas no anuladas."""
    if not variante_ids:
        return {}
    filas = db.execute(
        select(VentaDetalle.variante_id, func.sum(VentaDetalle.cantidad))
        .join(Venta, Venta.id == VentaDetalle.venta_id)
        .join(EstadoVenta, EstadoVenta.id == Venta.estado_id)
        .where(VentaDetalle.variante_id.in_(variante_ids), EstadoVenta.codigo != "anulada")
        .group_by(VentaDetalle.variante_id)
    ).all()
    return {variante_id: int(total) for variante_id, total in filas}


# ---- Pagos ----
# Operaciones internas de la sección Pagos, compartidas por más de un
# caso de uso:
# - `resolver_pago` (antes `_resolver_pago`): aplica el resultado de un pago
#   (aprobado/rechazado) UNA sola vez -- la usan CU-18 (webhook, polling y
#   la pantalla QR) y `cerrar_pagos_iniciados`.
# - `cerrar_pagos_iniciados`/`cancelar_venta_pendiente`: las usan CU-18 (al
#   reintentar o cancelar una compra) y `expirar_ventas_pendientes`.
# - `expirar_ventas_pendientes`: tarea programada sin actor humano, la
#   dispara la tarea periódica de `app/main.py`.
# - `cobrar_en_caja`: el pago presencial (lógica de `ProcesarPagoCaja`, CU-18),
#   extraída para que la sincronización offline (CU-25) cobre dentro de su
#   propia unidad de trabajo.
# - `construir_pago_respuesta`: para que el router arme PagoRespuesta sin
#   consultar `estado_pago`/`metodo_pago` directamente, sin importar qué CU
#   atendió la petición.


estado_pago_repo = EstadoPagoRepository()
metodo_pago_repo = MetodoPagoRepository()
pago_repo = PagoRepository()
transaccion_repo = TransaccionPasarelaRepository()


def construir_pago_respuesta(db: Session, pago: Pago) -> PagoRespuesta:
    """Para que el router arme PagoRespuesta sin consultar `estado_pago`/
    `metodo_pago` directamente."""
    estado = estado_pago_repo.obtener(db, pago.estado_id)
    metodo = db.get(MetodoPago, pago.metodo_pago_id)
    return PagoRespuesta(
        id=pago.id,
        venta_id=pago.venta_id,
        monto=pago.monto,
        referencia_externa=pago.referencia_externa,
        fecha=pago.fecha,
        metodo_pago=metodo.codigo if metodo else "",
        estado=estado.codigo,
    )


def primera_transaccion(db: Session, pago_id: int) -> TransaccionPasarela | None:
    """La transacción que dejó CU-18 al iniciar el pago: de ahí salen la
    pasarela y el id de transacción para consultarla."""
    return db.scalar(
        select(TransaccionPasarela)
        .where(TransaccionPasarela.pago_id == pago_id)
        .order_by(TransaccionPasarela.creado_en.asc())
        .limit(1)
    )


def empresa_de_transaccion(db: Session, pasarela: str, id_transaccion: str) -> int | None:
    """Empresa dueña de la transacción de pasarela con ese (pasarela, id), o
    `None` si no existe. Es la fuente de la empresa del webhook y de la
    pantalla QR, que llegan sin usuario: la lectura va SIN filtro de empresa
    (uno de los tres usos permitidos de `sin_filtro`) y devuelve solo el id
    de la empresa, nunca datos de la fila. Quien llama debe validar antes la
    firma del webhook."""
    return db.scalar(
        sin_filtro(
            select(TransaccionPasarela.empresa_id)
            .where(TransaccionPasarela.pasarela == pasarela, TransaccionPasarela.id_transaccion == id_transaccion)
            .order_by(TransaccionPasarela.creado_en.asc())
            .limit(1)
        )
    )


def _abandonar_pago(db: Session, pago: Pago, *, pasarela_codigo: str, motivo: str) -> None:
    """Marca 'rechazado' un pago 'iniciado' que nunca se completó. A
    diferencia de `resolver_pago(rechazado)`, NO toca la venta: quien
    llama decide si se reintenta (sigue 'pendiente_pago') o se cancela."""
    pago = pago_repo.obtener_bloqueado(db, pago.id)
    pago.estado_id = estado_pago_repo.obtener_por_codigo(db, "rechazado").id
    transaccion_repo.crear(
        db,
        TransaccionPasarela(
            pago_id=pago.id,
            pasarela=pasarela_codigo,
            id_transaccion=pago.referencia_externa,
            payload_envio=None,
            payload_respuesta={"origen": motivo},
            estado="rechazado",
        ),
    )


def cerrar_pagos_iniciados(db: Session, venta_id: int, *, motivo: str) -> bool:
    """Cierra los pagos 'iniciado' de una venta antes de reintentar o
    cancelar. A cada uno se le pregunta primero a la pasarela: si ya cobró,
    se aplica esa aprobación (confirma la venta, commit) y devuelve True
    para que quien llama NO inicie un segundo cobro ni anule una venta
    pagada. Si no cobró (o la pasarela no responde), el pago se abandona."""
    estado_iniciado = estado_pago_repo.obtener_por_codigo(db, "iniciado")
    for previo in pago_repo.listar_por_venta(db, venta_id):
        if previo.estado_id != estado_iniciado.id:
            continue
        primera = primera_transaccion(db, previo.id)
        estado_pasarela = "iniciado"
        if primera is not None and primera.id_transaccion is not None:
            try:
                estado_pasarela = obtener_pasarela(primera.pasarela).consultar_estado(primera.id_transaccion)
            except RuntimeError:
                estado_pasarela = "iniciado"
        if estado_pasarela == "aprobado":
            resolver_pago(
                db,
                previo.id,
                pasarela_codigo=primera.pasarela,
                id_transaccion=primera.id_transaccion,
                estado_resultado="aprobado",
                payload_respuesta={"origen": "consultar_estado", "estado": "aprobado"},
                commit=True,
            )
            return True
        metodo = db.get(MetodoPago, previo.metodo_pago_id)
        _abandonar_pago(db, previo, pasarela_codigo=primera.pasarela if primera else metodo.codigo, motivo=motivo)
    return False


def cancelar_venta_pendiente(db: Session, venta_id: int, *, motivo: str) -> None:
    venta = obtener_venta_bloqueada(db, venta_id)
    estado_venta = obtener_estado_codigo(db, venta.estado_id)
    if estado_venta != "pendiente_pago":
        raise ConflictoError(f"La venta está '{estado_venta}', no se puede cancelar")
    if cerrar_pagos_iniciados(db, venta.id, motivo=motivo):
        raise ConflictoError("Esta venta ya fue pagada")
    anular_venta(db, venta.id, commit=False, restaurar_carrito=True)
    db.commit()


def expirar_ventas_pendientes(db: Session) -> dict[str, int]:
    """Vence las ventas que siguen 'pendiente_pago' pasado
    VENTA_PENDIENTE_MINUTOS. No es un caso de uso del catálogo (no tiene
    actor humano): la dispara la tarea periódica de `app/main.py`. Cada
    venta es su propia transacción: una que falle no frena al resto. Si la
    pasarela sí había cobrado, la venta queda pagada en vez de anulada."""
    anuladas = pagadas = 0
    for venta_id in listar_ventas_pendientes_vencidas(db, get_settings().venta_pendiente_minutos):
        try:
            cancelar_venta_pendiente(db, venta_id, motivo="vencido")
            anuladas += 1
        except ConflictoError:
            db.rollback()
            if not es_venta_pendiente(db, venta_id):
                pagadas += 1
        except Exception:
            db.rollback()
            logger.exception("No se pudo vencer la venta %s", venta_id)
    return {"anuladas": anuladas, "pagadas": pagadas}


def expirar_ventas_de_todas_las_empresas(db: Session) -> dict[str, int]:
    """Corre `expirar_ventas_pendientes` una vez por cada empresa activa y
    suma los resultados (`anuladas` y `pagadas`). Una empresa que falla no
    frena a las demás y no aporta a la suma."""
    total = {"anuladas": 0, "pagadas": 0}
    for resultado in por_cada_empresa(db, plataforma_politicas.listar_empresas_activas(db), expirar_ventas_pendientes):
        if resultado is not None:
            total["anuladas"] += resultado["anuladas"]
            total["pagadas"] += resultado["pagadas"]
    return total


def _ya_resuelto(codigo_estado: str) -> bool:
    return codigo_estado != "iniciado"


def resolver_pago(
    db: Session,
    pago_id: int,
    *,
    pasarela_codigo: str,
    id_transaccion: str | None,
    estado_resultado: str,
    payload_respuesta: dict,
    commit: bool,
    avisar_compra: bool = True,
) -> Pago:
    """`avisar_compra` se pasa a `confirmar_venta` (el pedido sin conexión pasa False: tiene su propio aviso).

    Registra la evidencia y, si el pago todavía estaba 'iniciado',
    aplica el resultado (aprobado/rechazado) UNA sola vez. La usan tanto
    el webhook como el polling activo y la pantalla QR (todo CU-18): es el
    único lugar que decide si un resultado ya se aplicó o no (ahí vive la
    idempotencia).

    Bloquea la fila de `pago` (obtener_bloqueado) ANTES de leer su estado:
    si un webhook y un polling concurrente (o dos reintentos del mismo
    webhook) llegan casi juntos para el mismo pago, el segundo espera a
    que el primero comitee y recién ahí lee el estado ya actualizado, en
    vez de decidir con un `pago.estado_id` leído antes del commit del
    primero -- eso era lo que permitía el doble descuento de stock."""
    pago = pago_repo.obtener_bloqueado(db, pago_id)
    estado_actual = estado_pago_repo.obtener(db, pago.estado_id)

    transaccion_repo.crear(
        db,
        TransaccionPasarela(
            pago_id=pago.id,
            pasarela=pasarela_codigo,
            id_transaccion=id_transaccion,
            payload_envio=None,
            payload_respuesta=payload_respuesta,
            estado=estado_resultado,
        ),
    )

    if _ya_resuelto(estado_actual.codigo):
        # Idempotencia: este pago ya salió de 'iniciado' antes. No se
        # vuelve a confirmar/anular la venta ni a tocar el stock.
        _cerrar_tx(db, pago, commit)
        return pago

    if estado_resultado in ("aprobado", "rechazado"):
        estado_nuevo = estado_pago_repo.obtener_por_codigo(db, estado_resultado)
        pago.estado_id = estado_nuevo.id
        if estado_resultado == "aprobado":
            confirmar_venta(db, pago.venta_id, commit=False, avisar_compra=avisar_compra)
        else:
            anular_venta(db, pago.venta_id, commit=False, restaurar_carrito=True)
    # 'iniciado' repetido (sin novedad real): no cambia nada más.

    _cerrar_tx(db, pago, commit)
    return pago


def cobrar_en_caja(
    db: Session,
    usuario_id: int,
    venta_id: int,
    metodo_pago: str,
    monto_recibido: Decimal | None = None,
    commit: bool = True,
    fecha: dt.datetime | None = None,
) -> tuple[Pago, Decimal | None]:
    """Cobra una venta pendiente en caja: crea el pago aprobado y confirma la
    venta (descuenta el stock). Devuelve (pago, cambio); `cambio` solo existe
    en efectivo. Es la lógica de `ProcesarPagoCaja` (CU-18), sin cambios.

    `commit=False`: pago, confirmación de la venta y movimientos de stock
    quedan en flush; quien llama decide el commit o el rollback de todo.

    `fecha` (solo la sincronización offline): la fecha REAL del cobro, UTC naive.
    Sin ella, la de la base."""
    empleado = plataforma_politicas.obtener_empleado_por_usuario(db, usuario_id)
    if empleado is None:
        raise PermisoDenegadoError("Este usuario no es un empleado, no puede cobrar en caja")

    # Bloqueada desde el inicio: dos cobros simultáneos de la misma venta se
    # ponen en fila y el segundo ve el estado ya actualizado (más abajo).
    venta = obtener_venta_bloqueada(db, venta_id)
    # Cobrar confirma la venta y descuenta stock de SU sucursal: solo se
    # cobra en caja lo de la sucursal propia.
    plataforma_politicas.validar_acceso_sucursal(db, usuario_id, venta.sucursal_id)
    metodo = metodo_pago_repo.obtener_por_codigo(db, metodo_pago)
    if not metodo.disponible_caja:
        raise DomainError(f"'{metodo.codigo}' no está disponible en caja")

    cambio: Decimal | None = None
    if metodo.codigo == "efectivo":
        if monto_recibido is None:
            raise DomainError("El pago en efectivo necesita monto_recibido")
        if monto_recibido < venta.total:
            raise DomainError(f"El monto recibido ({monto_recibido}) no cubre el total ({venta.total})")
        cambio = monto_recibido - venta.total

    # Con la venta ya bloqueada: si otro cobro la pagó mientras tanto, se
    # rechaza antes de crear un segundo pago.
    _exigir_pendiente_pago(db, venta)

    estado_aprobado = estado_pago_repo.obtener_por_codigo(db, "aprobado")
    pago = Pago(
        venta_id=venta.id,
        metodo_pago_id=metodo.id,
        estado_id=estado_aprobado.id,
        monto=venta.total,
        # Solo si viene: pasar None dejaría el INSERT con NULL en vez del default de la base.
        **({"fecha": fecha} if fecha is not None else {}),
    )
    pago_repo.crear(db, pago)  # flush

    # El pago en caja se aprueba en el momento: no hay pasarela ni webhook,
    # así que acá mismo se dispara la confirmación de la venta.
    confirmar_venta(db, venta.id, usuario_id=usuario_id, commit=False)

    confirmar(db, commit)
    db.refresh(pago)
    return pago, cambio


def registrar_cobro_pasarela_aprobado(
    db: Session,
    venta: Venta,
    *,
    pasarela_codigo: str,
    id_transaccion: str,
    monto_usd: Decimal,
    tipo_cambio: Decimal,
    origen: str,
    avisar_compra: bool = True,
) -> Pago:
    """Deja asentado en el libro de pagos un cobro que la pasarela YA aprobó (sin que el cliente esté presente) y
    confirma la venta (descuenta el stock) en la unidad de trabajo del llamador: nunca confirma ni revierte.

    Es el mismo camino que el pago normal por pasarela: un `Pago` 'iniciado' con su primera `TransaccionPasarela`, y
    `resolver_pago(aprobado)` que agrega la evidencia, marca el pago y llama a `confirmar_venta`. Lo guardado en los
    payloads son montos y referencias, nunca el token con que se cobró."""
    metodo = metodo_pago_repo.obtener_por_codigo(db, pasarela_codigo)
    estado_iniciado = estado_pago_repo.obtener_por_codigo(db, "iniciado")
    pago = Pago(
        venta_id=venta.id,
        metodo_pago_id=metodo.id,
        estado_id=estado_iniciado.id,
        monto=venta.total,
        referencia_externa=id_transaccion,
    )
    pago_repo.crear(db, pago)  # flush: pago.id ya disponible
    transaccion_repo.crear(
        db,
        TransaccionPasarela(
            pago_id=pago.id,
            pasarela=pasarela_codigo,
            id_transaccion=id_transaccion,
            payload_envio={
                "monto": str(venta.total),
                "monto_usd": str(monto_usd),
                "tipo_cambio": str(tipo_cambio),
                "referencia": venta.codigo,
                "origen": origen,
            },
            payload_respuesta={"id_transaccion": id_transaccion},
            estado="iniciado",
        ),
    )
    return resolver_pago(
        db,
        pago.id,
        pasarela_codigo=pasarela_codigo,
        id_transaccion=id_transaccion,
        estado_resultado="aprobado",
        payload_respuesta={"origen": origen, "estado": "aprobado"},
        commit=False,
        avisar_compra=avisar_compra,
    )


# ---- PayPal guardado y pedido sin conexión (CU-18 y CU-13) ----

# Motivos estables de un pedido sin conexión rechazado (los lee el cliente: web y app).
MOTIVO_SIN_METODO_PAGO = "sin_metodo_pago"
MOTIVO_STOCK_INSUFICIENTE = "stock_insuficiente"
MOTIVO_TOTAL_SUPERA_MAXIMO = "total_supera_maximo"
MOTIVO_VARIANTE_INACTIVA = "variante_inactiva"
MOTIVO_PAGO_RECHAZADO = "pago_rechazado"
MOTIVO_PEDIDO_INVALIDO = "pedido_invalido"
MOTIVO_SUSCRIPCION_NO_ACTIVA = "suscripcion_no_activa"
MOTIVO_PEDIDO_VENCIDO = "pedido_vencido"
# PayPal SÍ cobró (un cobro incierto que al reintentar se confirmó) pero el pedido ya no se pudo completar: el dinero hay que
# devolverlo. A diferencia de todos los demás rechazos, aquí SÍ se cobró; el mensaje y el correo lo dicen.
MOTIVO_COBRO_A_REEMBOLSAR = "cobro_a_reembolsar"
# El motivo interno de la fila `incierto` (nunca sale por la API).
MOTIVO_COBRO_INCIERTO = "cobro_incierto"

# Cómo se dice cada motivo en el correo ("con el motivo en palabras").
MOTIVOS_EN_PALABRAS = {
    MOTIVO_SIN_METODO_PAGO: "no tienes un PayPal guardado",
    MOTIVO_STOCK_INSUFICIENTE: "ya no hay stock suficiente de alguna prenda",
    MOTIVO_TOTAL_SUPERA_MAXIMO: "el total subió por encima del máximo que aceptaste",
    MOTIVO_VARIANTE_INACTIVA: "alguna prenda ya no está disponible",
    MOTIVO_PAGO_RECHAZADO: "PayPal rechazó el cobro",
    MOTIVO_PEDIDO_INVALIDO: "el pedido no es válido",
    MOTIVO_SUSCRIPCION_NO_ACTIVA: "la tienda no está disponible por ahora",
    MOTIVO_PEDIDO_VENCIDO: "pasaron demasiados días sin conexión y el pedido venció",
    MOTIVO_COBRO_A_REEMBOLSAR: "cobramos tu PayPal pero ya no pudimos completar el pedido (por ejemplo, se agotó la prenda)",
}


class RechazoPedido(Exception):
    """Una decisión FINAL y esperada sobre un pedido sin conexión (no un error): el motivo estable y el texto para el
    cliente. Se guarda como `rechazado` y el cliente la recibe con HTTP 200."""

    def __init__(self, motivo: str, mensaje: str) -> None:
        super().__init__(mensaje)
        self.motivo = motivo
        self.mensaje = mensaje


class PagoIncierto(Exception):
    """El cobro no tiene un resultado conocido (PayPal o la red no respondieron bien): ni cobrado ni rechazado. No se
    guarda estado final; el cliente reintenta con la MISMA operación y PayPal, por el `PayPal-Request-Id`, no cobra
    dos veces. Trae el monto que se intentó cobrar (`total_bs`, `total_usd`) para dejar una marca `incierto` y, al
    reintentar, preguntarle a PayPal por ESE cobro antes de decidir cualquier otra cosa."""

    def __init__(self, mensaje: str, *, total_bs: Decimal | None = None, total_usd: Decimal | None = None) -> None:
        super().__init__(mensaje)
        self.total_bs = total_bs
        self.total_usd = total_usd


def enmascarar_correo(correo: str | None) -> str | None:
    """'juan@gmail.com' -> 'j***@gmail.com'. El correo completo de PayPal no se guarda ni se devuelve."""
    if not correo or "@" not in correo:
        return None
    usuario, _, dominio = correo.strip().partition("@")
    if not usuario or not dominio:
        return None
    return f"{usuario[0]}***@{dominio}"


def request_id_de_pedido(empresa_id: int, operacion_id) -> str:
    """El `PayPal-Request-Id` de un pedido: depende SOLO de la empresa y de la operación. Reintentar la misma operación
    manda la misma clave y PayPal devuelve el cobro original en vez de hacer otro."""
    return f"pd-{empresa_id}-{operacion_id}"


def paypal_rechazo_definitivo(error) -> bool:
    """¿Este error de PayPal es una DECISIÓN (el cobro no se hizo y no se hará con esta petición)? 400, 404 y 422 lo
    son: PayPal entendió la petición y la negó (instrumento rechazado, token de pago inexistente...). Todo lo demás
    (sin respuesta, 401, 403, 429, 5xx) es incierto: el cobro pudo haberse hecho. Un `DUPLICATE_REQUEST_ID` también es
    incierto: indica que esa clave ya se usó, o sea que un intento anterior pudo cobrar."""
    if "DUPLICATE_REQUEST_ID" in getattr(error, "problemas", ()):
        return False
    return getattr(error, "status_code", None) in (400, 404, 422)


def despachar_correo(mensaje: MensajeCorreo, programar_envio) -> None:
    """Envía el correo ya (sin `programar_envio`) o lo deja para DESPUÉS de responder (el router pasa
    `BackgroundTasks.add_task`). `enviar_correo_sin_romper` jamás lanza."""
    if programar_envio is None:
        enviar_correo_sin_romper(mensaje)
    else:
        programar_envio(enviar_correo_sin_romper, mensaje)


def destinatario_de_usuario(db: Session, usuario_id: int) -> tuple[str, str] | None:
    """(correo, nombre) de un usuario activo con correo, o None."""
    usuario = plataforma_politicas.obtener_usuario(db, usuario_id)
    if not usuario.activo or not usuario.email:
        return None
    return usuario.email, usuario.nombre


def construir_correo_pedido_diferido(
    *,
    para_email: str,
    nombre: str,
    nombre_empresa: str,
    sucursal: str,
    codigo_venta: str | None,
    total: Decimal | None,
    motivo: str | None,
) -> MensajeCorreo:
    """El aviso de un pedido sin conexión: 'Cobramos tu pedido' (con código, total en Bs y sucursal) si `codigo_venta`
    viene, o 'No pudimos cobrar tu pedido' (con el motivo en palabras). Todo dato variable se escapa en el HTML."""
    if codigo_venta is not None:
        asunto = f"Cobramos tu pedido {codigo_venta} · {nombre_empresa}"
        titulo = "Cobramos tu pedido"
        detalle = [
            f"Código: {codigo_venta}",
            f"Total: Bs {total}",
            f"Retíralo en: {sucursal}",
        ]
        cierre = "Pagamos con tu PayPal guardado mientras estabas sin conexión. Guarda este mensaje como constancia."
    else:
        asunto = f"No pudimos cobrar tu pedido · {nombre_empresa}"
        titulo = "No pudimos cobrar tu pedido"
        palabras = MOTIVOS_EN_PALABRAS.get(motivo or "", "hubo un problema con el pedido")
        detalle = [f"Motivo: {palabras}", f"Sucursal: {sucursal}"]
        if motivo == MOTIVO_COBRO_A_REEMBOLSAR:
            titulo = asunto_base = "No pudimos completar tu pedido"
            asunto = f"{asunto_base} · {nombre_empresa}"
            if total is not None:
                detalle.insert(0, f"Monto cobrado: Bs {total}")
            cierre = (
                "Sí se cobró tu PayPal, así que te devolveremos el dinero. Si no lo ves en unos días, "
                "escríbele a la tienda con este mensaje."
            )
        else:
            cierre = "No se te cobró nada. Puedes volver a hacer tu pedido cuando quieras."
    texto = f"Hola {nombre},\n\n{titulo} en {nombre_empresa}.\n" + "\n".join(detalle) + f"\n\n{cierre}\n"
    filas = "".join(f'<li style="margin:0 0 8px">{escape(linea)}</li>' for linea in detalle)
    html = (
        '<!doctype html><html lang="es"><body style="margin:0;background:#F7F5F1;font-family:Arial,Helvetica,sans-serif;'
        'color:#161412"><div style="max-width:480px;margin:0 auto;padding:24px">'
        '<p style="font-size:13px;letter-spacing:1px;text-transform:uppercase;color:#6B645C;margin:0 0 16px">'
        f"{escape(nombre_empresa)}</p>"
        f'<h1 style="font-size:22px;margin:0 0 12px">{escape(titulo)}</h1>'
        f'<p style="font-size:15px;line-height:1.5">Hola {escape(nombre)},</p>'
        f'<ul style="font-size:15px;line-height:1.5;padding-left:18px;margin:0 0 16px">{filas}</ul>'
        f'<p style="font-size:13px;line-height:1.5;color:#6B645C">{escape(cierre)}</p></div></body></html>'
    )
    return MensajeCorreo(para_email=para_email, para_nombre=nombre, asunto=asunto, html=html, texto=texto)


# ---- Compra confirmada: notificación y correo, UNA sola vez por venta (CU-18 / CU-13) ----------------------------
#
# `confirmar_venta` es el único punto que marca una venta como `pagada` (webhook, polling, QR, tareas, Caja, sincronización
# offline y pedido sin conexión pasan por él). Ahí se crea, en la MISMA transacción, la notificación `compra_confirmada`
# del comprador (su push sale solo, ver `plataforma.politicas.crear_notificacion`) y se anota la venta para el correo, que
# se manda recién cuando la transacción CONFIRMA, en el hilo aparte del push y con sesión propia. Un SAVEPOINT revertido
# deshace la notificación y el correo revalida que la venta siga pagada: nunca se avisa de algo que no quedó.

CLAVE_AVISO_COMPRA = "aviso_compra_pendientes"  # en `Session.info`: {(empresa_id, venta_id), ...}
TIPO_NOTIFICACION_COMPRA = "compra_confirmada"
ESTADOS_COMPRA_PAGADA = ("pagada", "entregada")


def enlace_comprobante_en_tienda(codigo_empresa: str, venta_id: int) -> str:
    """El enlace del correo: el detalle de la compra en la tienda de la empresa."""
    base = get_settings().frontend_public_url.rstrip("/")
    return f"{base}/t/{quote(codigo_empresa, safe='')}/mis-compras/{venta_id}"


def construir_enlace_verificacion(codigo_venta: str) -> str:
    """Lo que lleva el QR del comprobante: la venta en la Caja. Web y app solo dibujan este texto."""
    base = get_settings().frontend_public_url.rstrip("/")
    return f"{base}/caja?venta={quote(codigo_venta, safe='')}"


def _avisar_compra_confirmada(db: Session, venta: Venta) -> None:
    """Notificación (en esta transacción) y anotación del correo (para después del commit). Sin cliente, usuario inactivo
    o sin correo no se avisa. Nunca lanza: un aviso no puede deshacer un pago."""
    try:
        comprador = comprador_de_venta(db, venta)
        if comprador is None:
            return
        usuario_id = comprador[0]
        if plataforma_politicas.existe_notificacion(db, usuario_id, TIPO_NOTIFICACION_COMPRA, venta.id):
            return  # ya se avisó de esta venta
        mensaje = f"Tu compra {venta.codigo} por Bs {Decimal(venta.total):.2f} está pagada."
        with db.begin_nested():
            plataforma_politicas.crear_notificacion(
                db, usuario_id, "Compra confirmada", mensaje, TIPO_NOTIFICACION_COMPRA, venta.id, commit=False
            )
        if correo_configurado():
            db.info.setdefault(CLAVE_AVISO_COMPRA, set()).add((venta.empresa_id, venta.id))
    except Exception:  # noqa: BLE001 - el aviso es un extra
        logger.exception("aviso_compra_no_armado venta_id=%s", getattr(venta, "id", None))


@event.listens_for(Session, "after_commit")
def _despachar_correo_de_compra_al_confirmar(session: Session) -> None:
    """Cuando la transacción confirma de verdad, programa el correo de cada compra anotada. No lanza."""
    if session.in_nested_transaction():  # soltar un SAVEPOINT no es confirmar
        return
    pendientes = session.info.pop(CLAVE_AVISO_COMPRA, None)
    if not pendientes:
        return
    try:
        for empresa_id, venta_id in sorted(pendientes):
            plataforma_politicas.programar_en_segundo_plano(enviar_correo_de_compra_confirmada, empresa_id, venta_id)
    except Exception as exc:  # noqa: BLE001 - confirmar una venta jamás puede fallar por un correo
        logger.error("aviso_compra_no_programado tipo=%s", type(exc).__name__)


@event.listens_for(Session, "after_soft_rollback")
def _descartar_correo_de_compra_al_revertir(session: Session, previous_transaction) -> None:
    """Un rollback de la transacción completa descarta lo anotado; el de un SAVEPOINT no (el envío revalida la venta)."""
    if not previous_transaction.nested:
        session.info.pop(CLAVE_AVISO_COMPRA, None)


def enviar_correo_de_compra_confirmada(empresa_id: int, venta_id: int) -> None:
    """Segundo plano, sesión propia con la empresa fijada. Revalida que la venta siga pagada y manda el correo por Brevo.
    Nunca lanza."""
    try:
        db = plataforma_politicas.nueva_sesion_segundo_plano()
        try:
            fijar_empresa(db, empresa_id)
            mensaje = _armar_correo_de_compra(db, venta_id)
        finally:
            db.close()
        if mensaje is not None:
            enviar_correo_sin_romper(mensaje)
    except Exception as exc:  # noqa: BLE001 - mejor esfuerzo; el log lleva solo el tipo (nunca correos ni textos)
        logger.error("aviso_compra_correo_fallido venta_id=%s tipo=%s", venta_id, type(exc).__name__)


def _armar_correo_de_compra(db: Session, venta_id: int) -> MensajeCorreo | None:
    venta = venta_repo.obtener(db, venta_id)
    if obtener_estado_codigo(db, venta.estado_id) not in ESTADOS_COMPRA_PAGADA:
        return None
    destinatario = destinatario_de_venta(db, venta)
    if destinatario is None:
        return None
    empresa = plataforma_politicas.obtener_empresa_de_la_sesion(db)
    try:
        sucursal = plataforma_politicas.obtener_sucursal(db, venta.sucursal_id).nombre
    except NoEncontradoError:
        sucursal = ""
    lineas: list[tuple[str, int]] = []
    for linea in venta.detalle:
        variante = catalogo_politicas.buscar_variante(db, linea.variante_id)
        prenda = catalogo_politicas.describir_variante(db, variante) if variante is not None else "Prenda"
        lineas.append((prenda, linea.cantidad))
    return construir_correo_compra_confirmada(
        para_email=destinatario[0],
        nombre=destinatario[1],
        nombre_empresa=empresa.nombre,
        codigo_empresa=empresa.codigo,
        venta_id=venta.id,
        codigo_venta=venta.codigo,
        fecha=venta.fecha,
        sucursal=sucursal,
        lineas=lineas,
        subtotal=venta.subtotal,
        descuento=venta.descuento,
        costo_envio=venta.costo_envio,
        total=venta.total,
    )


def construir_correo_compra_confirmada(
    *,
    para_email: str,
    nombre: str,
    nombre_empresa: str,
    codigo_empresa: str,
    venta_id: int,
    codigo_venta: str,
    fecha: dt.datetime,
    sucursal: str,
    lineas: list[tuple[str, int]],
    subtotal: Decimal,
    descuento: Decimal,
    costo_envio: Decimal,
    total: Decimal,
) -> MensajeCorreo:
    """'Compra confirmada': código, fecha en hora de Bolivia, sucursal, prendas (nombre, talla, color y cantidad), importes
    y el botón 'Ver mi comprobante'. Sin imagen del QR ni adjuntos. Todo dato variable se escapa en el HTML."""
    asunto = f"Compra confirmada {codigo_venta} · {nombre_empresa}"
    enlace = enlace_comprobante_en_tienda(codigo_empresa, venta_id)
    cuando = _fecha_legible(fecha)

    def bs(monto: Decimal) -> str:
        return f"Bs {Decimal(monto):.2f}"

    importes = [("Subtotal", bs(subtotal))]
    if Decimal(descuento) > 0:
        importes.append(("Descuento", f"- {bs(descuento)}"))
    if Decimal(costo_envio) > 0:
        importes.append(("Envío", bs(costo_envio)))
    importes.append(("Total", bs(total)))

    datos = [("Código", codigo_venta), ("Fecha", cuando)]
    if sucursal:
        datos.append(("Sucursal", sucursal))

    texto = (
        f"Hola {nombre},\n\nTu compra en {nombre_empresa} está pagada.\n"
        + "\n".join(f"{etiqueta}: {valor}" for etiqueta, valor in datos)
        + "\n\nPrendas:\n"
        + "\n".join(f"- {prenda} (x{cantidad})" for prenda, cantidad in lineas)
        + "\n\n"
        + "\n".join(f"{etiqueta}: {valor}" for etiqueta, valor in importes)
        + f"\n\nVer mi comprobante: {enlace}\n"
    )
    filas_datos = "".join(
        f'<li style="margin:0 0 6px">{escape(etiqueta)}: <strong>{escape(valor)}</strong></li>' for etiqueta, valor in datos
    )
    filas_prendas = "".join(
        f'<li style="margin:0 0 6px">{escape(prenda)} (x{cantidad})</li>' for prenda, cantidad in lineas
    )
    filas_importes = "".join(
        f'<tr><td style="padding:2px 12px 2px 0">{escape(etiqueta)}</td><td style="text-align:right">{escape(valor)}</td></tr>'
        for etiqueta, valor in importes
    )
    html = (
        '<!doctype html><html lang="es"><body style="margin:0;background:#F7F5F1;font-family:Arial,Helvetica,sans-serif;'
        'color:#161412"><div style="max-width:480px;margin:0 auto;padding:24px">'
        '<p style="font-size:13px;letter-spacing:1px;text-transform:uppercase;color:#6B645C;margin:0 0 16px">'
        f"{escape(nombre_empresa)}</p>"
        '<h1 style="font-size:22px;margin:0 0 12px">Compra confirmada</h1>'
        f'<p style="font-size:15px;line-height:1.5">Hola {escape(nombre)}, tu compra está pagada.</p>'
        f'<ul style="font-size:15px;line-height:1.5;padding-left:18px;margin:0 0 16px">{filas_datos}</ul>'
        '<p style="font-size:15px;margin:0 0 6px"><strong>Prendas</strong></p>'
        f'<ul style="font-size:15px;line-height:1.5;padding-left:18px;margin:0 0 16px">{filas_prendas}</ul>'
        f'<table style="font-size:15px;margin:0 0 20px">{filas_importes}</table>'
        f'<p style="margin:0 0 16px"><a href="{escape(enlace, quote=True)}" style="display:inline-block;background:#151515;'
        'color:#F7F5F1;padding:12px 20px;text-decoration:none;border-radius:4px;font-size:15px">Ver mi comprobante</a></p>'
        '<p style="font-size:13px;line-height:1.5;color:#6B645C">Guarda este mensaje como constancia de tu compra.</p>'
        "</div></body></html>"
    )
    return MensajeCorreo(para_email=para_email, para_nombre=nombre, asunto=asunto, html=html, texto=texto)


# ---- Reembolsos (CU-17 y CU-18) -------------------------------------------------------------------------------------
#
# Un reembolso es el dinero que se le devuelve a quien compró: de una devolución SIN cambio de prenda (un cambio de talla
# o color no mueve dinero) o de anular un pago. Cada uno es una fila de `reembolso` con el método del pago original:
#   - efectivo y los métodos de la tienda (qr, tarjeta, transferencia): el dinero sale en el acto, de la mano del
#     personal, así que la fila nace `reembolsado` (el cierre de caja resta el de efectivo en el turno de ese momento);
#   - pasarela (PayPal, qr_online...): la fila nace `pendiente` en la transacción de la devolución y el dinero lo mueve
#     DESPUÉS `procesar_reembolso`, ya con esa transacción confirmada y con la clave de idempotencia de la pasarela.
# Cuando un reembolso se completa se avisa al comprador UNA vez: notificación (con su push) en la misma transacción y
# correo en segundo plano. Un reembolso `fallido` no avisa al cliente: lo ve el personal, que puede reintentarlo.

reembolso_repo = ReembolsoRepository()

TIPO_NOTIFICACION_REEMBOLSO = "reembolso"
_MONTO_USD_MINIMO = Decimal("0.01")
_COMO_SE_DEVOLVIO: dict[str, str] = {
    "efectivo": "en efectivo, en la tienda",
    "paypal": "a tu PayPal",
    "qr": "por QR",
    "qr_online": "por QR",
    "tarjeta": "a tu tarjeta",
    "transferencia": "por transferencia",
}


def descripcion_metodo_reembolso(metodo: str) -> str:
    """Cómo se le devolvió el dinero, en palabras para el aviso (según el método del pago original)."""
    return _COMO_SE_DEVOLVIO.get(metodo, "por el mismo medio con que pagaste")


def pago_aprobado_de_venta(db: Session, venta: Venta) -> Pago | None:
    """El pago aprobado de la venta (a lo sumo uno; la tienda no cobra una venta en partes) o `None` si no hay ninguno.
    Dos o más pagos aprobados no existen hoy: se rechaza para no devolver dinero a ciegas."""
    codigos = estado_pago_repo.mapa_codigos_por_id(db)
    aprobados = [pago for pago in pago_repo.listar_por_venta(db, venta.id) if codigos.get(pago.estado_id) == "aprobado"]
    if len(aprobados) > 1:
        raise ConflictoError("La venta tiene más de un pago aprobado: el reembolso no se puede hacer automáticamente")
    return aprobados[0] if aprobados else None


def monto_de_lineas_devueltas(lineas: Iterable[tuple[VentaDetalle, int]]) -> Decimal:
    """Lo que costaron las unidades devueltas, ya con el descuento de cada línea (`venta_detalle.subtotal` es neto):
    por cada línea, `subtotal x unidades devueltas / unidades vendidas`. El costo de envío no se devuelve."""
    total = Decimal("0")
    for detalle, cantidad in lineas:
        total += redondear(Decimal(detalle.subtotal) * cantidad / detalle.cantidad)
    return redondear(total)


def _usd_del_reembolso(
    db: Session, pago: Pago, monto: Decimal, restante: Decimal, usd_ya_devuelto: Decimal
) -> Decimal | None:
    """Los dólares de un reembolso de pasarela: proporcionales a lo que se cobró en dólares (el `monto_usd` que la
    transacción guardó al cobrar, al tipo de cambio de ESE día). El que termina de devolver el pago se lleva el resto,
    para que la suma de los reembolsos sea exacta. `None` si la pasarela no cobró en dólares (o el dato no existe)."""
    transaccion = primera_transaccion(db, pago.id)
    bruto = (transaccion.payload_envio or {}).get("monto_usd") if transaccion is not None else None
    if bruto is None:
        return None
    try:
        total_usd = Decimal(str(bruto))
    except InvalidOperation:
        return None
    if total_usd <= 0:
        return None
    if monto >= restante:
        return max(total_usd - usd_ya_devuelto, _MONTO_USD_MINIMO)
    return max(redondear(total_usd * monto / Decimal(pago.monto)), _MONTO_USD_MINIMO)


def crear_reembolso(
    db: Session,
    *,
    venta: Venta,
    pago: Pago,
    monto: Decimal,
    usuario_id: int,
    devolucion_id: int | None = None,
    contexto: ContextoAuditoria | None = None,
) -> Reembolso:
    """Registra el reembolso DENTRO de la transacción de quien llama (no confirma). Bloquea el pago, así que dos
    reembolsos simultáneos del mismo pago se ponen en fila y la suma nunca pasa de lo pagado (409). Los métodos de la
    tienda nacen `reembolsado`; los de pasarela, `pendiente` (ver `procesar_reembolso`)."""
    monto = redondear(Decimal(monto))
    if monto <= 0:
        raise DomainError("El monto a reembolsar debe ser mayor a cero")
    pago = pago_repo.obtener_bloqueado(db, pago.id)
    bs_ya, usd_ya = reembolso_repo.total_activo(db, pago.id)
    restante = Decimal(pago.monto) - bs_ya
    if monto > restante:
        raise ErrorFuncional(
            "reembolso_supera_lo_pagado",
            f"No se puede reembolsar más de lo pagado (quedan Bs {restante:.2f} por devolver de este pago)",
            409,
            restante=str(restante),
        )
    metodo = db.get(MetodoPago, pago.metodo_pago_id)
    por_pasarela = metodo is not None and metodo.requiere_pasarela
    fila = Reembolso(
        devolucion_id=devolucion_id,
        pago_id=pago.id,
        venta_id=venta.id,
        sucursal_id=venta.sucursal_id,
        metodo=metodo.codigo if metodo is not None else "",
        monto=monto,
        monto_usd=_usd_del_reembolso(db, pago, monto, restante, usd_ya) if por_pasarela else None,
        estado="pendiente",
        usuario_id=usuario_id,
    )
    reembolso_repo.crear(db, fila)
    if not por_pasarela:
        completar_reembolso(db, fila, venta=venta, referencia=None, contexto=contexto)
    return fila


def completar_reembolso(
    db: Session, reembolso: Reembolso, *, venta: Venta, referencia: str | None, contexto: ContextoAuditoria | None = None
) -> None:
    """El dinero salió: marca el reembolso, deja la bitácora, avisa al comprador (notificación; el correo lo programa
    quien llama después del commit) y, si ya se devolvió TODO el pago, el pago pasa a `reembolsado`. Todo en la
    transacción de quien llama (no confirma). Se llama una sola vez por reembolso: quien lo llama tiene la fila bloqueada
    o la acaba de crear."""
    reembolso.estado = "reembolsado"
    reembolso.referencia_externa = referencia or reembolso.referencia_externa
    reembolso.motivo_fallo = None
    reembolso.completado_en = ahora_utc_naive()
    db.flush()
    pago = pago_repo.obtener(db, reembolso.pago_id)
    if reembolso_repo.total_reembolsado(db, pago.id) >= Decimal(pago.monto):
        pago.estado_id = estado_pago_repo.obtener_por_codigo(db, "reembolsado").id
    datos: dict = {"venta_id": venta.id, "pago_id": pago.id, "metodo": reembolso.metodo, "monto": str(reembolso.monto)}
    if reembolso.devolucion_id is not None:
        datos["devolucion_id"] = reembolso.devolucion_id
    plataforma_politicas.registrar_bitacora_de(
        db, contexto, ENTIDAD_REEMBOLSO, reembolso.id, ACCION_REEMBOLSAR, datos
    )
    _notificar_reembolso(db, reembolso, venta)


def _notificar_reembolso(db: Session, reembolso: Reembolso, venta: Venta) -> None:
    """Notificación dentro del sistema (su push sale al confirmar la transacción). Sin cliente, usuario inactivo o sin
    correo no se avisa. No usa `existe_notificacion`: dos reembolsos parciales de la misma venta avisan cada uno. Nunca
    lanza: un aviso no puede deshacer un reembolso."""
    try:
        comprador = comprador_de_venta(db, venta)
        if comprador is None:
            return
        mensaje = (
            f"Reembolsamos Bs {Decimal(reembolso.monto):.2f} de tu compra {venta.codigo} "
            f"{descripcion_metodo_reembolso(reembolso.metodo)}."
        )
        with db.begin_nested():
            plataforma_politicas.crear_notificacion(
                db, comprador[0], "Te devolvimos tu dinero", mensaje, TIPO_NOTIFICACION_REEMBOLSO, venta.id, commit=False
            )
    except Exception:  # noqa: BLE001 - el aviso es un extra
        logger.exception("aviso_reembolso_no_armado reembolso_id=%s", getattr(reembolso, "id", None))


def reembolsar_devolucion(
    db: Session,
    *,
    venta: Venta,
    devolucion: Devolucion,
    lineas_sin_cambio: list[tuple[VentaDetalle, int]],
    usuario_id: int,
    contexto: ContextoAuditoria | None = None,
) -> list[Reembolso]:
    """Crea el reembolso de las líneas de una devolución que NO piden cambio de prenda (en la transacción de quien
    llama). Sin líneas así (un cambio de talla o color) no hay dinero que devolver. Si la venta no tiene un pago aprobado
    (no debería ocurrir en una venta pagada) se deja constancia en el log y no se inventa un reembolso."""
    if not lineas_sin_cambio:
        return []
    pago = pago_aprobado_de_venta(db, venta)
    if pago is None:
        logger.warning("devolucion_sin_pago_aprobado venta_id=%s devolucion_id=%s", venta.id, devolucion.id)
        return []
    monto = monto_de_lineas_devueltas(lineas_sin_cambio)
    return [
        crear_reembolso(
            db,
            venta=venta,
            pago=pago,
            monto=monto,
            usuario_id=usuario_id,
            devolucion_id=devolucion.id,
            contexto=contexto,
        )
    ]


def reembolsar_pago_completo(
    db: Session, *, venta: Venta, pago: Pago, usuario_id: int, contexto: ContextoAuditoria | None = None
) -> Reembolso | None:
    """Anular un pago devuelve TODO lo que falte por devolver de él (lo ya devuelto en devoluciones se descuenta). Si ya
    no falta nada, el pago solo pasa a `reembolsado`. Devuelve el reembolso nuevo, o `None` si no hizo falta crear uno."""
    pago = pago_repo.obtener_bloqueado(db, pago.id)
    bs_ya, _usd = reembolso_repo.total_activo(db, pago.id)
    restante = Decimal(pago.monto) - bs_ya
    if restante <= 0:
        if reembolso_repo.total_reembolsado(db, pago.id) >= Decimal(pago.monto):
            pago.estado_id = estado_pago_repo.obtener_por_codigo(db, "reembolsado").id
        return None
    return crear_reembolso(db, venta=venta, pago=pago, monto=restante, usuario_id=usuario_id, contexto=contexto)


def procesar_reembolso(db: Session, reembolso_id: int, *, contexto: ContextoAuditoria | None = None) -> Reembolso:
    """Paso 2 de un reembolso de pasarela, con su transacción de origen YA confirmada: le pide a la pasarela que devuelva
    el dinero (con la clave de idempotencia del propio reembolso: repetirlo no devuelve dos veces) y confirma el
    resultado. La fila queda bloqueada durante la llamada, así que dos reintentos a la vez se ponen en fila.
    - La pasarela lo hizo: `reembolsado` (aviso al comprador).
    - La pasarela lo aceptó pero aún no lo completó: sigue `pendiente`, con su referencia.
    - La pasarela dijo que no: `fallido` (definitivo; el personal puede reintentar).
    - La pasarela no respondió: sigue `pendiente` (se reintenta con la misma clave).
    Funciona también para reintentar un `fallido`. Un reembolso ya `reembolsado` no se vuelve a pedir."""
    reembolso = reembolso_repo.obtener_bloqueado(db, reembolso_id)
    if reembolso.estado == "reembolsado":
        return reembolso
    venta = venta_repo.obtener(db, reembolso.venta_id)
    transaccion = primera_transaccion(db, reembolso.pago_id)
    try:
        if transaccion is None or not transaccion.id_transaccion:
            raise ReembolsoRechazado("sin_transaccion")
        try:
            pasarela = obtener_pasarela(transaccion.pasarela)
        except ValueError as exc:
            raise ReembolsoRechazado("pasarela_desconocida") from exc
        resultado = pasarela.reembolsar(
            id_transaccion=transaccion.id_transaccion,
            monto=Decimal(reembolso.monto),
            monto_usd=reembolso.monto_usd,
            request_id=f"reembolso-{reembolso.empresa_id}-{reembolso.id}",
        )
    except ReembolsoRechazado as rechazo:
        reembolso.estado = "fallido"
        reembolso.motivo_fallo = rechazo.motivo[:60]
        plataforma_politicas.registrar_bitacora_de(
            db,
            contexto,
            ENTIDAD_REEMBOLSO,
            reembolso.id,
            ACCION_FALLAR,
            {"venta_id": venta.id, "metodo": reembolso.metodo, "motivo": rechazo.motivo},
        )
        db.commit()
        db.refresh(reembolso)
        return reembolso
    except RuntimeError as exc:  # la pasarela no respondió: no se sabe si devolvió; se reintenta con la misma clave
        logger.warning("reembolso_sin_respuesta reembolso_id=%s tipo=%s", reembolso.id, type(exc).__name__)
        reembolso.motivo_fallo = "sin_respuesta"
        db.commit()
        db.refresh(reembolso)
        return reembolso

    if resultado.completado:
        completar_reembolso(db, reembolso, venta=venta, referencia=resultado.referencia, contexto=contexto)
    else:
        reembolso.referencia_externa = resultado.referencia
        reembolso.motivo_fallo = None
    db.commit()
    db.refresh(reembolso)
    return reembolso


def finalizar_reembolsos(
    db: Session,
    reembolsos: list[Reembolso],
    *,
    contexto: ContextoAuditoria | None = None,
    programar_envio=None,
) -> tuple[list[Reembolso], bool]:
    """Después de CONFIRMAR la transacción que los creó: mueve el dinero de los reembolsos de pasarela y manda el correo
    de los que ya salieron. Devuelve los reembolsos tal como quedaron y si algún correo quedó programado. NUNCA lanza: la
    devolución o la anulación ya están confirmadas y un fallo de la pasarela o del correo no las deshace."""
    resultado: list[Reembolso] = []
    for reembolso in reembolsos:
        try:
            if reembolso.estado == "pendiente":
                reembolso = procesar_reembolso(db, reembolso.id, contexto=contexto)
            else:
                db.refresh(reembolso)
        except Exception:  # noqa: BLE001 - lo ya confirmado no se deshace por un fallo de la pasarela
            db.rollback()
            logger.exception("reembolso_no_procesado reembolso_id=%s", reembolso.id)
            reembolso = reembolso_repo.obtener(db, reembolso.id)
        resultado.append(reembolso)
    return resultado, avisar_reembolsos_por_correo(db, resultado, programar_envio)


def avisar_reembolsos_por_correo(db: Session, reembolsos: Iterable[Reembolso], programar_envio=None) -> bool:
    """El correo de constancia de cada reembolso que ya salió (Brevo, en segundo plano si el router pasa
    `BackgroundTasks.add_task`). Sin cliente, sin correo o sin Brevo no se manda; nunca lanza. Devuelve si programó alguno."""
    programado = False
    for reembolso in reembolsos:
        if reembolso.estado != "reembolsado":
            continue
        try:
            if not correo_configurado():
                return False
            venta = venta_repo.obtener(db, reembolso.venta_id)
            destinatario = destinatario_de_venta(db, venta)
            if destinatario is None:
                continue
            empresa = plataforma_politicas.obtener_empresa_de_la_sesion(db)
            try:
                sucursal = plataforma_politicas.obtener_sucursal(db, venta.sucursal_id).nombre
            except NoEncontradoError:
                sucursal = ""
            devolucion = devolucion_repo.obtener(db, reembolso.devolucion_id) if reembolso.devolucion_id else None
            mensaje = construir_correo_reembolso(
                para_email=destinatario[0],
                nombre=destinatario[1],
                nombre_empresa=empresa.nombre,
                codigo_empresa=empresa.codigo,
                venta_id=venta.id,
                codigo_venta=venta.codigo,
                codigo_devolucion=devolucion.codigo if devolucion is not None else None,
                sucursal=sucursal,
                monto=reembolso.monto,
                metodo=reembolso.metodo,
                fecha=reembolso.completado_en or ahora_utc_naive(),
                referencia=reembolso.referencia_externa,
            )
            despachar_correo(mensaje, programar_envio)
            programado = True
        except Exception:  # noqa: BLE001 - el correo es un extra: jamás deshace el reembolso
            logger.exception("aviso_reembolso_correo_no_armado reembolso_id=%s", reembolso.id)
    return programado


def construir_correo_reembolso(
    *,
    para_email: str,
    nombre: str,
    nombre_empresa: str,
    codigo_empresa: str,
    venta_id: int,
    codigo_venta: str,
    codigo_devolucion: str | None,
    sucursal: str,
    monto: Decimal,
    metodo: str,
    fecha: dt.datetime,
    referencia: str | None,
) -> MensajeCorreo:
    """'Te devolvimos tu dinero': constancia del reembolso con la compra, la devolución (si la hubo), el monto, cómo se
    devolvió, la fecha en hora de Bolivia, la sucursal y la referencia de la pasarela. Todo dato variable se escapa."""
    asunto = f"Te devolvimos tu dinero · compra {codigo_venta} · {nombre_empresa}"
    enlace = enlace_comprobante_en_tienda(codigo_empresa, venta_id)
    datos = [("Compra", codigo_venta)]
    if codigo_devolucion:
        datos.append(("Devolución", codigo_devolucion))
    datos += [
        ("Monto devuelto", f"Bs {Decimal(monto):.2f}"),
        ("Cómo", descripcion_metodo_reembolso(metodo)),
        ("Fecha", _fecha_legible(fecha)),
    ]
    if sucursal:
        datos.append(("Sucursal", sucursal))
    if referencia:
        datos.append(("Referencia", referencia))

    texto = (
        f"Hola {nombre},\n\nTe devolvimos tu dinero de {nombre_empresa}.\n"
        + "\n".join(f"{etiqueta}: {valor}" for etiqueta, valor in datos)
        + f"\n\nVer mi compra: {enlace}\n\nGuarda este mensaje como constancia de tu reembolso.\n"
    )
    filas = "".join(
        f'<li style="margin:0 0 6px">{escape(etiqueta)}: <strong>{escape(valor)}</strong></li>' for etiqueta, valor in datos
    )
    html = (
        '<!doctype html><html lang="es"><body style="margin:0;background:#F7F5F1;font-family:Arial,Helvetica,sans-serif;'
        'color:#161412"><div style="max-width:480px;margin:0 auto;padding:24px">'
        '<p style="font-size:13px;letter-spacing:1px;text-transform:uppercase;color:#6B645C;margin:0 0 16px">'
        f"{escape(nombre_empresa)}</p>"
        '<h1 style="font-size:22px;margin:0 0 12px">Te devolvimos tu dinero</h1>'
        f'<p style="font-size:15px;line-height:1.5">Hola {escape(nombre)}, este es el detalle de tu reembolso.</p>'
        f'<ul style="font-size:15px;line-height:1.5;padding-left:18px;margin:0 0 16px">{filas}</ul>'
        f'<p style="margin:0 0 16px"><a href="{escape(enlace, quote=True)}" style="display:inline-block;background:#151515;'
        'color:#F7F5F1;padding:12px 20px;text-decoration:none;border-radius:4px;font-size:15px">Ver mi compra</a></p>'
        '<p style="font-size:13px;line-height:1.5;color:#6B645C">Guarda este mensaje como constancia de tu reembolso.</p>'
        "</div></body></html>"
    )
    return MensajeCorreo(para_email=para_email, para_nombre=nombre, asunto=asunto, html=html, texto=texto)


# ---- Caja: turnos y cierres (E21) ------------------------------------------------------------------------------------
#
# La caja es de la SUCURSAL: a lo sumo un turno abierto por sucursal a la vez. El efectivo que se espera en el cajón es
#   monto inicial + efectivo cobrado en la sucursal durante el turno - efectivo reembolsado durante el turno.
# El efectivo cobrado se filtra por el MÉTODO de pago (no por el canal de la venta), sin importar qué cajero registró cada
# venta. Lo cobrado con QR, tarjeta o transferencia en la tienda y las compras online son solo informativos. Una venta
# hecha sin conexión cuenta en el turno que cubría su hora REAL de cobro, aunque se sincronice horas después: el cierre
# ya hecho no cambia y el detalle muestra la diferencia como `ajuste_posterior`.
# Un turno no pasa del día (en hora de Bolivia): al terminar el día se cierra solo, SIN conteo (`cerrada_auto`); un
# supervisor puede completar ese conteo una vez, dentro de `HORAS_PARA_COMPLETAR_CONTEO`.

caja_turno_repo = CajaTurnoRepository()

HORAS_PARA_COMPLETAR_CONTEO = 72


@dataclass(frozen=True)
class ResumenTurno:
    """El dinero de un turno en una ventana de tiempo (ver el comentario de arriba)."""

    ventas_efectivo: Decimal
    cantidad_ventas: int
    reembolsos_efectivo: Decimal
    ventas_otros_metodos: Decimal
    ventas_online: Decimal
    cantidad_ventas_online: int
    monto_esperado: Decimal


def resumen_de_turno(db: Session, turno: CajaTurno, hasta: dt.datetime | None = None) -> ResumenTurno:
    """Calcula el dinero del turno entre su apertura y `hasta` (por defecto, su cierre o, si sigue abierto, ahora)."""
    limite = hasta if hasta is not None else (turno.cierre_en or ahora_utc_naive())
    empresa, sucursal, desde = turno.empresa_id, turno.sucursal_id, turno.apertura_en
    cobrado, cantidad = caja_turno_repo.efectivo_cobrado(db, empresa, sucursal, desde, limite)
    devuelto = caja_turno_repo.reembolsos_en_efectivo(db, empresa, sucursal, desde, limite)
    otros = caja_turno_repo.cobrado_en_otros_metodos(db, empresa, sucursal, desde, limite)
    online, cantidad_online = caja_turno_repo.ventas_online(db, empresa, sucursal, desde, limite)
    return ResumenTurno(
        ventas_efectivo=redondear(cobrado),
        cantidad_ventas=cantidad,
        reembolsos_efectivo=redondear(devuelto),
        ventas_otros_metodos=redondear(otros),
        ventas_online=redondear(online),
        cantidad_ventas_online=cantidad_online,
        monto_esperado=redondear(Decimal(turno.monto_inicial) + cobrado - devuelto),
    )


def fin_de_dia_bolivia(instante: dt.datetime) -> dt.datetime:
    """El instante (UTC naive) en que termina el día de Bolivia en que cae `instante` (UTC naive)."""
    return dia_bolivia(instante.replace(tzinfo=dt.timezone.utc))[2]


def limites_de_dias_bolivia(
    desde: dt.date | None, hasta: dt.date | None
) -> tuple[dt.datetime | None, dt.datetime | None]:
    """De un rango de días de Bolivia (ambos incluidos) a instantes UTC naive: `[inicio de desde, inicio del día después
    de hasta)`. Un extremo `None` queda abierto."""

    def a_dia(fecha: dt.date) -> tuple[dt.date, dt.datetime, dt.datetime]:
        return dia_bolivia(dt.datetime.combine(fecha, dt.time(12), tzinfo=ZONA_BOLIVIA))

    return (a_dia(desde)[1] if desde is not None else None), (a_dia(hasta)[2] if hasta is not None else None)


def es_supervisor_de_caja(db: Session, usuario_id: int) -> bool:
    return PERMISO_CAJA_SUPERVISAR in permisos_de_usuario(db, usuario_id)


def _error_turno_ya_abierto() -> ErrorFuncional:
    return ErrorFuncional("turno_ya_abierto", "Ya hay un turno abierto en esta sucursal", 409)


def _error_turno_cerrado() -> ErrorFuncional:
    return ErrorFuncional("turno_cerrado", "Este turno ya está cerrado", 409)


def _aplicar_foto_del_cierre(turno: CajaTurno, resumen: ResumenTurno) -> None:
    """Guarda lo que el sistema sabía al cerrar: un cierre pasado no cambia aunque después llegue una venta tarde."""
    turno.ventas_efectivo = resumen.ventas_efectivo
    turno.reembolsos_efectivo = resumen.reembolsos_efectivo
    turno.monto_esperado = resumen.monto_esperado
    turno.cantidad_ventas = resumen.cantidad_ventas
    turno.ventas_otros_metodos = resumen.ventas_otros_metodos


def sucursal_de_caja(db: Session, usuario_id: int, sucursal_id: int | None) -> int:
    """La sucursal sobre la que opera la caja esta persona: la suya si está limitada a una (403 si pide otra); quien opera
    todas las sucursales (el administrador) tiene que indicarla. Debe existir en la empresa, estar activa y no ser un
    depósito (allí no se cobra)."""
    propia = plataforma_politicas.sucursal_asignada(db, usuario_id)
    if propia is not None:
        if sucursal_id is not None and sucursal_id != propia:
            raise PermisoDenegadoError("No tienes acceso a esa sucursal")
        sucursal_id = propia
    elif sucursal_id is None:
        raise DomainError("Indica la sucursal de la caja")
    sucursal = plataforma_politicas.obtener_sucursal(db, sucursal_id)  # 404 si no existe o es de otra empresa
    if not sucursal.activo or sucursal.es_deposito:
        raise DomainError("En esa sucursal no se cobra: elige otra")
    return sucursal_id


def cerrar_turnos_vencidos(db: Session, sucursal_id: int | None = None) -> int:
    """Cierra solos, SIN conteo, los turnos que ya pasaron del día en que se abrieron (hora de Bolivia): el cierre queda a
    las 24:00 de ese día y el esperado se congela. Cada uno se bloquea y se vuelve a mirar antes de tocarlo. Corre como
    tarea periódica y también al abrir o consultar un turno, así un turno olvidado de ayer nunca bloquea a la sucursal
    aunque la tarea no haya corrido. Devuelve cuántos cerró."""
    ahora = ahora_utc_naive()
    cerrados = 0
    for turno in caja_turno_repo.listar_abiertos(db, None if sucursal_id is None else [sucursal_id]):
        fin = fin_de_dia_bolivia(turno.apertura_en)
        if ahora < fin:
            continue
        bloqueado = caja_turno_repo.obtener_bloqueado(db, turno.id)
        if bloqueado.estado != "abierta":
            db.rollback()
            continue
        resumen = resumen_de_turno(db, bloqueado, fin)
        _aplicar_foto_del_cierre(bloqueado, resumen)
        bloqueado.estado = "cerrada_auto"
        bloqueado.cierre_en = fin
        bloqueado.cerrado_por_id = None
        plataforma_politicas.registrar_bitacora(
            db,
            None,
            ENTIDAD_CIERRE_CAJA,
            bloqueado.id,
            ACCION_CIERRE_AUTOMATICO,
            {"sucursal_id": bloqueado.sucursal_id, "monto_esperado": str(resumen.monto_esperado)},
        )
        db.commit()
        cerrados += 1
    return cerrados


def vencer_turnos_de_todas_las_empresas(db: Session) -> int:
    """`cerrar_turnos_vencidos` una vez por cada empresa activa (tarea periódica, sin actor humano). Una empresa que
    falla no frena a las demás."""
    resultados = por_cada_empresa(db, plataforma_politicas.listar_empresas_activas(db), cerrar_turnos_vencidos)
    return sum(r or 0 for r in resultados)


def abrir_turno(
    db: Session, usuario_id: int, datos: TurnoAbrir, contexto: ContextoAuditoria | None = None
) -> CajaTurno:
    sucursal_id = sucursal_de_caja(db, usuario_id, datos.sucursal_id)
    cerrar_turnos_vencidos(db, sucursal_id)
    if caja_turno_repo.obtener_abierto_de_sucursal(db, sucursal_id) is not None:
        raise _error_turno_ya_abierto()
    turno = CajaTurno(
        sucursal_id=sucursal_id,
        abierto_por_id=usuario_id,
        estado="abierta",
        apertura_en=ahora_utc_naive(),
        monto_inicial=redondear(Decimal(datos.monto_inicial)),
        observacion_apertura=(datos.observacion or "").strip() or None,
        pendientes_declarados=0,
    )
    try:
        # En un SAVEPOINT: dos aperturas simultáneas chocan en el índice único parcial y la segunda recibe el 409.
        with db.begin_nested():
            caja_turno_repo.crear(db, turno)
    except IntegrityError as exc:
        db.rollback()
        raise _error_turno_ya_abierto() from exc
    plataforma_politicas.registrar_bitacora_de(
        db,
        contexto,
        ENTIDAD_CIERRE_CAJA,
        turno.id,
        ACCION_ABRIR,
        {"sucursal_id": sucursal_id, "monto_inicial": str(turno.monto_inicial)},
    )
    db.commit()
    db.refresh(turno)
    return turno


def cerrar_turno(
    db: Session, usuario_id: int, turno_id: int, datos: TurnoCerrar, contexto: ContextoAuditoria | None = None
) -> CajaTurno:
    """Cierra el turno contando el efectivo. Lo cierra quien lo abrió o un supervisor de la sucursal. La diferencia es
    `contado - esperado`; si no es cero la observación es obligatoria."""
    existente = caja_turno_repo.obtener(db, turno_id)  # 404 si no existe o es de otra empresa
    cerrar_turnos_vencidos(db, existente.sucursal_id)
    turno = caja_turno_repo.obtener_bloqueado(db, turno_id)
    plataforma_politicas.validar_acceso_sucursal(db, usuario_id, turno.sucursal_id)
    if turno.estado != "abierta":
        raise _error_turno_cerrado()
    permisos = permisos_de_usuario(db, usuario_id)
    es_supervisor = PERMISO_CAJA_SUPERVISAR in permisos
    if not es_supervisor:
        if turno.abierto_por_id != usuario_id:
            raise ErrorFuncional(
                "turno_de_otro_cajero", "Este turno lo abrió otra persona: pide a un supervisor que lo cierre", 403
            )
        if PERMISO_VENTAS_PRESENCIAL not in permisos:
            raise PermisoDenegadoError(f"Falta el permiso '{PERMISO_VENTAS_PRESENCIAL}'")

    hasta = ahora_utc_naive()
    resumen = resumen_de_turno(db, turno, hasta)
    contado = redondear(Decimal(datos.efectivo_contado))
    diferencia = redondear(contado - resumen.monto_esperado)
    observacion = (datos.observacion or "").strip()
    if diferencia != 0 and not observacion:
        raise ErrorFuncional(
            "observacion_requerida", "El conteo no coincide con lo esperado: explica la diferencia en la observación", 400
        )
    _aplicar_foto_del_cierre(turno, resumen)
    turno.estado = "cerrada"
    turno.cierre_en = hasta
    turno.cerrado_por_id = usuario_id
    turno.efectivo_contado = contado
    turno.diferencia = diferencia
    turno.pendientes_declarados = datos.pendientes_sin_sincronizar
    turno.observacion_cierre = observacion or None
    plataforma_politicas.registrar_bitacora_de(
        db,
        contexto,
        ENTIDAD_CIERRE_CAJA,
        turno.id,
        ACCION_CERRAR,
        {
            "sucursal_id": turno.sucursal_id,
            "monto_esperado": str(resumen.monto_esperado),
            "efectivo_contado": str(contado),
            "diferencia": str(diferencia),
            "cantidad_ventas": resumen.cantidad_ventas,
            "por_supervisor": turno.abierto_por_id != usuario_id,
        },
    )
    db.commit()
    db.refresh(turno)
    return turno


def completar_conteo_de_turno(
    db: Session, usuario_id: int, turno_id: int, datos: TurnoCompletarConteo, contexto: ContextoAuditoria | None = None
) -> CajaTurno:
    """Un supervisor cuenta el cajón de un turno que se cerró solo: una sola vez y dentro de `HORAS_PARA_COMPLETAR_CONTEO`
    después del cierre. La diferencia se calcula contra el esperado que se congeló al cerrar."""
    turno = caja_turno_repo.obtener_bloqueado(db, turno_id)
    plataforma_politicas.validar_acceso_sucursal(db, usuario_id, turno.sucursal_id)
    if turno.estado != "cerrada_auto":
        raise ErrorFuncional(
            "conteo_no_aplica", "Solo se completa el conteo de un turno que se cerró automáticamente", 409
        )
    if turno.efectivo_contado is not None:
        raise ErrorFuncional("conteo_ya_registrado", "El conteo de este turno ya se registró", 409)
    ahora = ahora_utc_naive()
    if ahora > turno.cierre_en + dt.timedelta(hours=HORAS_PARA_COMPLETAR_CONTEO):
        raise ErrorFuncional(
            "conteo_fuera_de_plazo",
            f"Pasaron más de {HORAS_PARA_COMPLETAR_CONTEO} horas: ya no se puede completar el conteo",
            409,
        )
    contado = redondear(Decimal(datos.efectivo_contado))
    turno.efectivo_contado = contado
    turno.diferencia = redondear(contado - Decimal(turno.monto_esperado))
    turno.conteo_en = ahora
    turno.conteo_por_id = usuario_id
    turno.observacion_conteo = datos.observacion.strip()
    plataforma_politicas.registrar_bitacora_de(
        db,
        contexto,
        ENTIDAD_CIERRE_CAJA,
        turno.id,
        ACCION_COMPLETAR_CONTEO,
        {"sucursal_id": turno.sucursal_id, "efectivo_contado": str(contado), "diferencia": str(turno.diferencia)},
    )
    db.commit()
    db.refresh(turno)
    return turno


def ajuste_posterior_de_turno(db: Session, turno: CajaTurno) -> Decimal | None:
    """Solo en un turno ya cerrado: el esperado recalculado HOY con la misma ventana menos el que se guardó al cerrar.
    Positivo = llegaron ventas sincronizadas tarde; negativo = algo se devolvió o anuló después."""
    if turno.estado == "abierta" or turno.cierre_en is None or turno.monto_esperado is None:
        return None
    return redondear(resumen_de_turno(db, turno, turno.cierre_en).monto_esperado - Decimal(turno.monto_esperado))


def monto_inicial_sugerido(db: Session, sucursal_id: int) -> Decimal | None:
    """Para abrir el siguiente turno: lo que se contó al cerrar el anterior (si ese se cerró solo y nadie lo contó, el
    esperado), o `None` si la sucursal nunca tuvo un turno."""
    ultimo = caja_turno_repo.ultimo_cerrado_de_sucursal(db, sucursal_id)
    if ultimo is None:
        return None
    return Decimal(ultimo.efectivo_contado if ultimo.efectivo_contado is not None else ultimo.monto_esperado)


def _nombre_completo(usuario) -> str | None:
    if usuario is None:
        return None
    return f"{usuario.nombre} {usuario.apellido or ''}".strip()


def construir_turno_respuesta(
    db: Session,
    turno: CajaTurno,
    *,
    ver_esperado: bool,
    detalle: bool = False,
    usuarios: dict | None = None,
    sucursales: dict[int, str] | None = None,
) -> TurnoRespuesta | TurnoDetalleRespuesta:
    """Arma la respuesta. CIERRE CIEGO: `monto_esperado` y `resumen` solo van con `ver_esperado` (el supervisor, o quien
    ya cerró el turno). `usuarios` y `sucursales` permiten resolver los nombres de un listado en lote."""
    if usuarios is None:
        ids = {turno.abierto_por_id, turno.cerrado_por_id, turno.conteo_por_id} - {None}
        usuarios = plataforma_politicas.obtener_usuarios_por_ids(db, list(ids))
    if sucursales is not None and turno.sucursal_id in sucursales:
        sucursal_nombre = sucursales[turno.sucursal_id]
    else:
        sucursal_nombre = plataforma_politicas.obtener_sucursal(db, turno.sucursal_id).nombre

    resumen = None
    monto_esperado = None
    if ver_esperado:
        if turno.estado == "abierta":
            vivo = resumen_de_turno(db, turno)
            resumen = ResumenTurnoRespuesta(**vivo.__dict__)
        else:
            # Un turno cerrado muestra la foto que se guardó; lo informativo de la ventana se recalcula.
            actual = resumen_de_turno(db, turno, turno.cierre_en)
            resumen = ResumenTurnoRespuesta(
                ventas_efectivo=turno.ventas_efectivo,
                cantidad_ventas=turno.cantidad_ventas or 0,
                reembolsos_efectivo=turno.reembolsos_efectivo,
                ventas_otros_metodos=turno.ventas_otros_metodos,
                ventas_online=actual.ventas_online,
                cantidad_ventas_online=actual.cantidad_ventas_online,
                monto_esperado=turno.monto_esperado,
            )
        monto_esperado = resumen.monto_esperado

    conteo_hasta = None
    if turno.estado == "cerrada_auto" and turno.efectivo_contado is None and turno.cierre_en is not None:
        conteo_hasta = turno.cierre_en + dt.timedelta(hours=HORAS_PARA_COMPLETAR_CONTEO)

    datos = dict(
        id=turno.id,
        sucursal_id=turno.sucursal_id,
        sucursal_nombre=sucursal_nombre,
        estado=turno.estado,
        apertura_en=turno.apertura_en,
        abierto_por_id=turno.abierto_por_id,
        abierto_por_nombre=_nombre_completo(usuarios.get(turno.abierto_por_id)),
        monto_inicial=turno.monto_inicial,
        observacion_apertura=turno.observacion_apertura,
        cierre_en=turno.cierre_en,
        cerrado_por_id=turno.cerrado_por_id,
        cerrado_por_nombre=_nombre_completo(usuarios.get(turno.cerrado_por_id)),
        cierre_automatico=turno.estado == "cerrada_auto",
        efectivo_contado=turno.efectivo_contado if (ver_esperado or turno.estado == "abierta") else None,
        diferencia=turno.diferencia if ver_esperado else None,
        pendientes_declarados=turno.pendientes_declarados,
        observacion_cierre=turno.observacion_cierre,
        conteo_en=turno.conteo_en,
        conteo_por_nombre=_nombre_completo(usuarios.get(turno.conteo_por_id)),
        observacion_conteo=turno.observacion_conteo,
        conteo_hasta=conteo_hasta,
        monto_esperado=monto_esperado,
        resumen=resumen,
    )
    if not detalle:
        return TurnoRespuesta(**datos)
    reembolsos = [
        ReembolsoRespuesta.model_validate(fila)
        for fila in db.scalars(
            select(Reembolso)
            .where(
                Reembolso.empresa_id == turno.empresa_id,
                Reembolso.sucursal_id == turno.sucursal_id,
                Reembolso.estado == "reembolsado",
                Reembolso.completado_en >= turno.apertura_en,
                Reembolso.completado_en <= (turno.cierre_en or ahora_utc_naive()),
            )
            .order_by(Reembolso.completado_en, Reembolso.id)
            .limit(200)
        )
    ]
    return TurnoDetalleRespuesta(
        **datos, ajuste_posterior=ajuste_posterior_de_turno(db, turno), reembolsos=reembolsos
    )
