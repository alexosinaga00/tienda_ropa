"""Máquina de estados y operaciones internas del paquete `reservas`, que
no son casos de uso del catálogo de 43:
- `validar_transicion` (antes `_transicionar`): valida y aplica un cambio
  de estado, registrando el historial. La usan CU-18 y CU-20: no se
  duplica en los dos archivos.
- `validar_propietario_o_staff`: valida acceso a una reserva (el personal,
  solo a las de su sucursal). La usan CU-17 y CU-18.
- `expirar_reservas_vencidas`: tarea programada sin actor humano, expuesta
  por un endpoint protegido con token de servicio.
- `mapa_codigos_estado`, `obtener_reserva_para_venta` y
  `reporte_reservas_por_estado`: consultas que el router y otros paquetes
  (`ventas`, `reportes`) necesitan sin tocar las tablas de reservas
  directamente.
"""

import datetime as dt
import logging

from sqlalchemy.orm import Session

from app.core.deps import ParametrosPeriodo
from app.core.exceptions import DomainError, PermisoDenegadoError
from app.core.security import permisos_de_usuario
from app.inventario.politicas import liberar_stock
from app.organizacion import politicas as organizacion_politicas
from app.reservas.models import Reserva, ReservaHistorial
from app.reservas.repository import EstadoReservaRepository, ReservaRepository
from app.seguridad.politicas import obtener_perfil_cliente

logger = logging.getLogger(__name__)

estado_repo = EstadoReservaRepository()
reserva_repo = ReservaRepository()

PERMISO_STAFF = "reservas.gestionar_sucursal"

# Transiciones válidas iniciadas por una persona (staff). 'expirada' no
# está acá a propósito: solo la genera expirar_reservas_vencidas(), nunca
# un PUT.
TRANSICIONES_VALIDAS: dict[str, set[str]] = {
    "pendiente": {"preparada", "cancelada"},
    "preparada": {"en_prueba", "cancelada"},
    "en_prueba": {"completada"},
}


def es_staff(db: Session, usuario_id: int) -> bool:
    return PERMISO_STAFF in permisos_de_usuario(db, usuario_id)


def validar_propietario_o_staff(db: Session, reserva: Reserva, usuario_id: int) -> None:
    if es_staff(db, usuario_id):
        # El personal solo accede a las reservas de su propia sucursal.
        organizacion_politicas.validar_acceso_sucursal(db, usuario_id, reserva.sucursal_id)
        return
    cliente = obtener_perfil_cliente(db, usuario_id)
    if cliente is None or reserva.cliente_id != cliente.id:
        raise PermisoDenegadoError("No tenés acceso a esta reserva")


def validar_transicion(
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


def mapa_codigos_estado(db: Session) -> dict[int, str]:
    """Para que el router arme ReservaRespuesta sin consultar
    `estado_reserva` directamente."""
    return estado_repo.mapa_codigos_por_id(db)


def obtener_reserva_para_venta(db: Session, reserva_id: int) -> Reserva:
    """Para que `ventas` (venta presencial en caja) lea, sin consultar
    `reserva`/`reserva_detalle` directamente, las líneas que un cliente
    decidió comprar al probarse la reserva -- el cliente de la venta sale
    de `reserva.cliente_id`, no hace falta que el cajero ya lo conozca. Sin
    chequeo de propiedad: es una acción de staff, no del cliente dueño.
    CU-20 (registrar selección) ya deja la reserva en 'completada' en
    cuanto todas las líneas tienen decisión -- acá solo se valida que ese
    paso ya haya pasado.

    Bloquea la fila de la reserva: dos cajeros cobrando la misma reserva a
    la vez esperan uno al otro, y el segundo ve la venta del primero (la
    guardia de doble facturación vive en ventas, CU-25)."""
    reserva = reserva_repo.obtener_bloqueado(db, reserva_id)
    estado = estado_repo.obtener(db, reserva.estado_id)
    if estado.codigo != "completada":
        raise DomainError(f"La reserva está en estado '{estado.codigo}', todavía no se puede facturar")
    return reserva


def reporte_reservas_por_estado(
    db: Session, periodo: ParametrosPeriodo, sucursal_id: int | None = None
) -> list[dict]:
    """Para `reportes`: cantidad de reservas por estado en el período, sin
    saber nada de si terminaron en una venta -- esa cuenta cruzada la hace
    `reportes`, no acá."""
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
        estado_repo.obtener_por_codigo(db, codigo).id for codigo in ("pendiente", "preparada")
    ]
    ids_vencidas = [reserva.id for reserva in reserva_repo.listar_vencidas(db, ahora, estados_activos_ids)]
    estado_expirada_id = estado_repo.obtener_por_codigo(db, "expirada").id

    expiradas = 0
    for reserva_id in ids_vencidas:
        try:
            # Bloqueada y con el estado releído: si el cliente la canceló (o
            # el personal la avanzó) mientras tanto, ya no se toca.
            reserva = reserva_repo.obtener_bloqueado(db, reserva_id)
            if reserva.estado_id not in estados_activos_ids:
                db.rollback()
                continue
            for linea in reserva.detalle:
                liberar_stock(db, linea.variante_id, reserva.sucursal_id, linea.cantidad, commit=False)
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
