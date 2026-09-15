"""Reservas: crear_reserva() valida disponibilidad (vía
inventario.service.reservar_stock, que ya bloquea la fila de stock) y la
franja horaria contra el horario de la sucursal, y notifica a los
empleados de esa sucursal -- todo en una sola transacción.

registrar_seleccion() es el punto delicado: el enunciado no dice qué pasa
si en una misma llamada solo se decide parte de las líneas. Acá una línea
ya decidida (seleccionada IS NOT NULL) nunca se vuelve a tocar, y la
reserva solo pasa a 'completada' cuando TODAS las líneas ya tienen una
decisión -- una selección parcial dentro de una llamada, o repartida en
varias llamadas, deja el resto tal cual sin liberar de más ni completar
antes de tiempo.
"""

import datetime as dt
import secrets

from sqlalchemy.orm import Session

from app.catalogo import service as catalogo_service
from app.core import service as core_service
from app.core.deps import ParametrosPeriodo
from app.core.exceptions import ConflictoError, DomainError, NoEncontradoError, PermisoDenegadoError
from app.core.security import permisos_de_usuario
from app.inventario import service as inventario_service
from app.organizacion import service as organizacion_service
from app.reservas.models import Reserva, ReservaDetalle, ReservaHistorial
from app.reservas.repository import EstadoReservaRepository, ReservaRepository
from app.reservas.schemas import ReservaCrear, SeleccionActualizar
from app.seguridad import service as seguridad_service

estado_repo = EstadoReservaRepository()
reserva_repo = ReservaRepository()

PERMISO_STAFF = "reservas.gestionar_sucursal"

# Transiciones válidas iniciadas por una persona (staff). 'expirada' no
# está acá a propósito: solo la genera expirar_reservas(), nunca un PUT.
TRANSICIONES_VALIDAS: dict[str, set[str]] = {
    "pendiente": {"preparada", "cancelada"},
    "preparada": {"en_prueba", "cancelada"},
    "en_prueba": {"completada"},
}


def _generar_codigo(db: Session) -> str:
    for _ in range(5):
        codigo = f"RES-{secrets.token_hex(4).upper()}"
        if reserva_repo.obtener_por_codigo(db, codigo) is None:
            return codigo
    raise DomainError("No se pudo generar un código único para la reserva, reintentá")


def _es_staff(db: Session, usuario_id: int) -> bool:
    return PERMISO_STAFF in permisos_de_usuario(db, usuario_id)


def _validar_propietario_o_staff(db: Session, reserva: Reserva, usuario_id: int) -> None:
    if _es_staff(db, usuario_id):
        return
    cliente = seguridad_service.obtener_perfil_cliente(db, usuario_id)
    if cliente is None or reserva.cliente_id != cliente.id:
        raise PermisoDenegadoError("No tenés acceso a esta reserva")


def _transicionar(
    db: Session, reserva: Reserva, codigo_nuevo: str, usuario_id: int | None, comentario: str, commit: bool = True
) -> Reserva:
    estado_actual = estado_repo.obtener(db, reserva.estado_id)
    validos = TRANSICIONES_VALIDAS.get(estado_actual.codigo, set())
    if codigo_nuevo not in validos:
        raise DomainError(f"No se puede pasar de '{estado_actual.codigo}' a '{codigo_nuevo}'")

    estado_nuevo = estado_repo.obtener_por_codigo(db, codigo_nuevo)
    reserva.estado_id = estado_nuevo.id
    db.add(
        ReservaHistorial(
            reserva_id=reserva.id, estado_id=estado_nuevo.id, usuario_id=usuario_id, comentario=comentario
        )
    )
    if commit:
        db.commit()
        db.refresh(reserva)
    else:
        db.flush()
    return reserva


# ---- Crear --------------------------------------------------------------------


def crear_reserva(db: Session, usuario_id: int, datos: ReservaCrear) -> Reserva:
    cliente = seguridad_service.obtener_perfil_cliente(db, usuario_id)
    organizacion_service.obtener_sucursal(db, datos.sucursal_id)  # 404 si no existe
    if not organizacion_service.atiende_al_publico(db, datos.sucursal_id):
        raise DomainError("Esa sucursal es un depósito y no recibe clientes: elegí otra para tu reserva")

    if datos.hora_visita_desde >= datos.hora_visita_hasta:
        raise DomainError("hora_visita_desde debe ser anterior a hora_visita_hasta")

    # dia_semana: 1=lunes ... 7=domingo (date.isoweekday()), igual que se
    # pide al crear un horario_sucursal.
    dia_semana = datos.fecha_visita.isoweekday()
    horario = organizacion_service.obtener_horario_dia(db, datos.sucursal_id, dia_semana)
    if horario is None:
        raise DomainError("La sucursal no atiende ese día")
    if datos.hora_visita_desde < horario.hora_apertura or datos.hora_visita_hasta > horario.hora_cierre:
        raise DomainError("La franja horaria elegida está fuera del horario de atención de la sucursal")

    for linea in datos.detalle:
        catalogo_service.obtener_variante(db, linea.variante_id)  # 404 si no existe

    estado_pendiente = estado_repo.obtener_por_codigo(db, "pendiente")
    fecha_hasta = dt.datetime.combine(datos.fecha_visita, datos.hora_visita_hasta, tzinfo=dt.timezone.utc)
    fecha_expiracion = fecha_hasta + dt.timedelta(hours=24)

    reserva = Reserva(
        codigo=_generar_codigo(db),
        cliente_id=cliente.id,
        sucursal_id=datos.sucursal_id,
        estado_id=estado_pendiente.id,
        fecha_visita=datos.fecha_visita,
        hora_visita_desde=datos.hora_visita_desde,
        hora_visita_hasta=datos.hora_visita_hasta,
        fecha_expiracion=fecha_expiracion,
        observacion=datos.observacion,
    )
    reserva.detalle = [
        ReservaDetalle(variante_id=linea.variante_id, cantidad=linea.cantidad) for linea in datos.detalle
    ]
    reserva_repo.crear(db, reserva)  # flush: reserva.id ya queda disponible

    # Reserva el stock de cada línea. Si una no tiene disponibilidad
    # suficiente, ninguna de las anteriores queda aplicada (commit=False:
    # toda la creación es una sola transacción).
    for linea in reserva.detalle:
        inventario_service.reservar_stock(
            db, linea.variante_id, datos.sucursal_id, linea.cantidad, commit=False
        )

    db.add(
        ReservaHistorial(
            reserva_id=reserva.id, estado_id=estado_pendiente.id, usuario_id=usuario_id, comentario="Reserva creada"
        )
    )

    for empleado in organizacion_service.listar_empleados_sucursal(db, datos.sucursal_id):
        core_service.crear_notificacion(
            db,
            empleado.usuario_id,
            titulo="Nueva reserva",
            mensaje=f"Reserva {reserva.codigo} para el {datos.fecha_visita.isoformat()}",
            tipo="reserva",
            referencia_id=reserva.id,
            commit=False,
        )

    db.commit()
    db.refresh(reserva)
    return reserva


# ---- Consultas ------------------------------------------------------------------


def mapa_codigos_estado(db: Session) -> dict[int, str]:
    """Para que el router arme ReservaRespuesta sin consultar
    `estado_reserva` directamente."""
    return estado_repo.mapa_codigos_por_id(db)


def obtener_reserva(db: Session, reserva_id: int, usuario_id: int) -> Reserva:
    reserva = reserva_repo.obtener(db, reserva_id)
    _validar_propietario_o_staff(db, reserva, usuario_id)
    return reserva


def listar_mis_reservas(db: Session, usuario_id: int) -> list[Reserva]:
    cliente = seguridad_service.obtener_perfil_cliente(db, usuario_id)
    return reserva_repo.listar_por_cliente(db, cliente.id)


def listar_reservas_sucursal(db: Session, sucursal_id: int) -> list[Reserva]:
    organizacion_service.obtener_sucursal(db, sucursal_id)
    return reserva_repo.listar_por_sucursal(db, sucursal_id)


def reporte_reservas_por_estado(
    db: Session, periodo: ParametrosPeriodo, sucursal_id: int | None = None
) -> list[dict]:
    """Para `reportes` (P6.3): cantidad de reservas por estado en el
    período, sin saber nada de si terminaron en una venta -- esa cuenta
    cruzada la hace `reportes.service`, no acá."""
    return reserva_repo.contar_por_estado(db, periodo.desde, periodo.hasta, sucursal_id)


def obtener_reserva_para_venta(db: Session, reserva_id: int) -> Reserva:
    """Para que `ventas` (venta presencial en caja) lea, sin consultar
    `reserva`/`reserva_detalle` directamente, las líneas que un cliente
    decidió comprar al probarse la reserva -- el cliente de la venta sale
    de `reserva.cliente_id`, no hace falta que el cajero ya lo conozca. Sin
    chequeo de propiedad: es una acción de staff, no del cliente dueño.
    `registrar_seleccion` ya deja la reserva en 'completada' en cuanto
    todas las líneas tienen decisión (ver su docstring); acá solo se
    valida que ese paso ya haya pasado -- no hay una transición aparte que
    "complete" la reserva al vender, esa ya ocurrió antes."""
    reserva = reserva_repo.obtener(db, reserva_id)
    estado = estado_repo.obtener(db, reserva.estado_id)
    if estado.codigo != "completada":
        raise DomainError(f"La reserva está en estado '{estado.codigo}', todavía no se puede facturar")
    return reserva


# ---- Transiciones ---------------------------------------------------------------


def preparar_reserva(db: Session, reserva_id: int, usuario_id: int) -> Reserva:
    reserva = reserva_repo.obtener(db, reserva_id)
    _transicionar(db, reserva, "preparada", usuario_id, "Prendas preparadas", commit=False)
    for linea in reserva.detalle:
        linea.preparada = True

    cliente = seguridad_service.obtener_cliente(db, reserva.cliente_id)
    core_service.crear_notificacion(
        db,
        cliente.usuario_id,
        titulo="Tu reserva está lista",
        mensaje=f"La reserva {reserva.codigo} ya tiene las prendas preparadas, te esperamos.",
        tipo="reserva_preparada",
        referencia_id=reserva.id,
        commit=False,
    )

    db.commit()
    db.refresh(reserva)
    return reserva


def confirmar_llegada(db: Session, reserva_id: int, usuario_id: int) -> Reserva:
    reserva = reserva_repo.obtener(db, reserva_id)
    return _transicionar(db, reserva, "en_prueba", usuario_id, "Cliente llegó a la sucursal")


def registrar_seleccion(db: Session, reserva_id: int, usuario_id: int, datos: SeleccionActualizar) -> Reserva:
    reserva = reserva_repo.obtener(db, reserva_id)
    estado_actual = estado_repo.obtener(db, reserva.estado_id)
    if estado_actual.codigo != "en_prueba":
        raise ConflictoError(
            f"La reserva está en estado '{estado_actual.codigo}', no se puede registrar selección"
        )

    detalle_por_variante = {linea.variante_id: linea for linea in reserva.detalle}

    for entrada in datos.lineas:
        linea = detalle_por_variante.get(entrada.variante_id)
        if linea is None:
            raise NoEncontradoError(f"La variante {entrada.variante_id} no está en esta reserva")
        if linea.seleccionada is not None:
            # Ya decidida antes (esta llamada u otra anterior): no se
            # vuelve a tocar, para no liberar/reservar dos veces.
            raise ConflictoError(f"La variante {entrada.variante_id} ya tiene una selección registrada")

        linea.seleccionada = entrada.seleccionada
        if not entrada.seleccionada:
            inventario_service.liberar_stock(db, linea.variante_id, reserva.sucursal_id, linea.cantidad, commit=False)

    db.flush()

    # Solo pasa a 'completada' si TODAS las líneas ya tienen decisión; una
    # selección parcial dentro de esta llamada (o repartida en varias)
    # deja la reserva en 'en_prueba'.
    if all(linea.seleccionada is not None for linea in reserva.detalle):
        _transicionar(db, reserva, "completada", usuario_id, "Selección completa", commit=False)

    db.commit()
    db.refresh(reserva)
    return reserva


def cancelar_reserva(db: Session, reserva_id: int, usuario_id: int) -> Reserva:
    reserva = reserva_repo.obtener(db, reserva_id)
    _validar_propietario_o_staff(db, reserva, usuario_id)

    estado_actual = estado_repo.obtener(db, reserva.estado_id)
    if estado_actual.codigo not in ("pendiente", "preparada"):
        raise ConflictoError(f"No se puede cancelar una reserva en estado '{estado_actual.codigo}'")

    for linea in reserva.detalle:
        inventario_service.liberar_stock(db, linea.variante_id, reserva.sucursal_id, linea.cantidad, commit=False)

    return _transicionar(db, reserva, "cancelada", usuario_id, "Cancelada", commit=True)


# ---- Tarea de sistema -------------------------------------------------------------


def expirar_reservas(db: Session) -> int:
    """Libera el stock de todas las reservas vencidas que sigan en estado
    pendiente o preparada. Cada reserva se procesa (liberación + cambio de
    estado) como su propia transacción, así una reserva con datos raros no
    frena a las demás."""
    ahora = dt.datetime.now(dt.timezone.utc)
    estados_activos_ids = [
        estado_repo.obtener_por_codigo(db, codigo).id for codigo in ("pendiente", "preparada")
    ]
    vencidas = reserva_repo.listar_vencidas(db, ahora, estados_activos_ids)
    estado_expirada = estado_repo.obtener_por_codigo(db, "expirada")

    for reserva in vencidas:
        for linea in reserva.detalle:
            inventario_service.liberar_stock(
                db, linea.variante_id, reserva.sucursal_id, linea.cantidad, commit=False
            )
        reserva.estado_id = estado_expirada.id
        db.add(
            ReservaHistorial(
                reserva_id=reserva.id,
                estado_id=estado_expirada.id,
                usuario_id=None,
                comentario="Expirada automáticamente",
            )
        )
        db.commit()

    return len(vencidas)
