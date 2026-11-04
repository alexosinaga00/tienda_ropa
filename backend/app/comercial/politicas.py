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
from decimal import ROUND_HALF_UP, Decimal
from html import escape
from typing import TYPE_CHECKING

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.catalogo import politicas as catalogo_politicas
from app.catalogo.casos_uso.cu09_gestionar_inventario import ConsultarDisponibilidadSucursal
from app.comercial import repository as comercial_repo
from app.comercial.models import (
    Carrito,
    CarritoDetalle,
    EstadoVenta,
    MetodoPago,
    Pago,
    Promocion,
    Reserva,
    ReservaDetalle,
    ReservaHistorial,
    TransaccionPasarela,
    Venta,
    VentaDetalle,
)
from app.comercial.pasarela import obtener_pasarela
from app.comercial.repository import (
    CarritoRepository,
    DevolucionRepository,
    EstadoPagoRepository,
    EstadoReservaRepository,
    EstadoVentaRepository,
    MetodoPagoRepository,
    PagoRepository,
    PromocionRepository,
    ReservaRepository,
    TransaccionPasarelaRepository,
    VentaRepository,
)
from app.comercial.schemas import PagoRespuesta, ReservaCrear
from app.core.config import get_settings
from app.core.codigos import generar_codigo
from app.core.permisos import PERMISO_STAFF_RESERVAS, PERMISO_STAFF_VENTAS
from app.core.deps import ParametrosPeriodo
from app.core.correo import MensajeCorreo
from app.core.tiempo import ZONA_BOLIVIA, ahora_utc_naive, hoy_utc
from app.core.exceptions import (
    ConflictoError,
    DomainError,
    PermisoDenegadoError,
    PlazoCambioVencidoError,
    StockInsuficienteError,
)
from app.core.repository import confirmar
from app.core.security import permisos_de_usuario
from app.core.tenant import por_cada_empresa, sin_filtro
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
    ahora = dt.datetime.now(dt.timezone.utc)
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


def confirmar_venta(db: Session, venta_id: int, *, usuario_id: int | None = None, commit: bool = True) -> Venta:
    """Para que la sección de Pagos confirme la venta cuando su pago pasa a 'aprobado'
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


def validar_plazo_cambio(fecha_venta: dt.datetime, plazo_horas: int, ahora: dt.datetime) -> None:
    """Pura: 409 si `ahora` pasó `fecha_venta + plazo_horas`. El límite es
    inclusivo (a las 24:00:00 exactas aún se acepta; a las 24:00:01 no)."""
    if ahora > fecha_venta + dt.timedelta(hours=plazo_horas):
        raise PlazoCambioVencidoError(
            "El plazo para cambiar prendas de esta venta ya venció: se hizo hace "
            f"{_duracion_legible(ahora - fecha_venta)} y el plazo es de {_plazo_legible(plazo_horas)}."
        )


def exigir_plazo_cambio(db: Session, venta: Venta, ahora: dt.datetime | None = None) -> None:
    """Aplica el plazo de la empresa de la sesión a la venta. Se cuenta desde
    `Venta.fecha`, que en una venta offline es la fecha de la operación y no la
    de la sincronización."""
    validar_plazo_cambio(
        venta.fecha, plataforma_politicas.obtener_plazo_cambio_horas(db), ahora or ahora_utc_naive()
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


def destinatario_de_venta(db: Session, venta: Venta) -> tuple[str, str] | None:
    """(correo, nombre) de quien compró, o None si la venta no tiene cliente (p. ej. una venta presencial sin
    cuenta) o su usuario está inactivo."""
    if venta.cliente_id is None:
        return None
    cliente = plataforma_politicas.obtener_cliente(db, venta.cliente_id)
    usuario = plataforma_politicas.obtener_usuario(db, cliente.usuario_id)
    if not usuario.activo or not usuario.email:
        return None
    return usuario.email, usuario.nombre


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
) -> Pago:
    """Registra la evidencia y, si el pago todavía estaba 'iniciado',
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
            confirmar_venta(db, pago.venta_id, commit=False)
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
