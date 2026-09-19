"""CU-15 — Registrar movimiento de inventario

Actor: Encargado de sucursal, Administrador.
Precondición: sesión con el permiso inventario.gestionar; la variante y la
sucursal existen y la sucursal es la del empleado (salvo alcance global;
en una transferencia, la de origen o la de destino según el paso).
Postcondición: el stock de la sucursal queda actualizado y el movimiento
queda registrado en el kardex con usuario, fecha y saldo resultante.

Caso de uso COMPUESTO: agrupa el ajuste manual y la transferencia entre
sucursales, con su kardex. Ninguno de los dos reimplementa el cálculo de
saldo o de costo promedio: ambos delegan en
inventario.politicas.actualizar_stock_operacion.
"""

import datetime as dt
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.exceptions import ConflictoError, DomainError, PermisoDenegadoError
from app.catalogo import politicas as catalogo_politicas
from app.inventario.models import MovimientoInventario, Transferencia, TransferenciaDetalle, TipoMovimiento
from app.inventario.politicas import actualizar_stock_operacion
from app.inventario.repository import MovimientoRepository, StockRepository, TipoMovimientoRepository, TransferenciaRepository
from app.inventario.schemas import MovimientoCrear, TransferenciaCrear
from app.organizacion import politicas as organizacion_politicas


def _validar_participa_en_transferencia(db: Session, usuario_id: int, transferencia_o_datos) -> None:
    """Una transferencia la ve y la opera el personal de cualquiera de sus
    dos sucursales (origen o destino); el alcance global, todas."""
    propia = organizacion_politicas.sucursal_asignada(db, usuario_id)
    extremos = (transferencia_o_datos.sucursal_origen_id, transferencia_o_datos.sucursal_destino_id)
    if propia is not None and propia not in extremos:
        raise PermisoDenegadoError("No tenés acceso a esa transferencia")


class RegistrarMovimientoInventario:
    def __init__(self) -> None:
        self._movimientos = MovimientoRepository()
        self._tipos = TipoMovimientoRepository()
        self._stock = StockRepository()
        self._transferencias = TransferenciaRepository()

    # -- Soporte para el kardex ------------------------------------------------

    def listar_tipos_movimiento(self, db: Session) -> list[TipoMovimiento]:
        return self._tipos.listar(db)

    def mapa_codigos_tipo_movimiento(self, db: Session) -> dict[int, str]:
        """Para que el router arme MovimientoRespuesta sin consultar
        `tipo_movimiento` directamente al listar el kardex."""
        return {tipo.id: tipo.codigo for tipo in self._tipos.listar(db)}

    def listar_kardex(
        self, db: Session, usuario_id: int, variante_id: int, sucursal_id: int
    ) -> list[MovimientoInventario]:
        catalogo_politicas.obtener_variante(db, variante_id)
        organizacion_politicas.obtener_sucursal(db, sucursal_id)
        organizacion_politicas.validar_acceso_sucursal(db, usuario_id, sucursal_id)
        return self._movimientos.listar_por_variante_sucursal(db, variante_id, sucursal_id)

    # -- Movimientos y ajustes ----------------------------------------------------

    def registrar_movimiento(self, db: Session, usuario_id: int, datos: MovimientoCrear) -> MovimientoInventario:
        """POST /inventario/movimientos. Antes el router llamaba directo a
        actualizar_stock_operacion (regla 5); acá además se valida que la
        sucursal sea la del empleado."""
        organizacion_politicas.validar_acceso_sucursal(db, usuario_id, datos.sucursal_id)
        return actualizar_stock_operacion(
            db,
            variante_id=datos.variante_id,
            sucursal_id=datos.sucursal_id,
            tipo_movimiento_codigo=datos.tipo_movimiento_codigo,
            cantidad=datos.cantidad,
            costo_unitario=datos.costo_unitario,
            referencia_tipo=datos.referencia_tipo,
            referencia_id=datos.referencia_id,
            usuario_id=usuario_id,
            observacion=datos.observacion,
        )

    def registrar_ajuste(
        self,
        db: Session,
        variante_id: int,
        sucursal_id: int,
        cantidad: int,
        usuario_id: int,
        observacion: str | None,
    ) -> MovimientoInventario:
        """Envoltorio delgado sobre actualizar_stock_operacion(): traduce el
        signo de `cantidad` (positivo = sobrante, negativo = faltante) al
        tipo de movimiento correspondiente."""
        if cantidad == 0:
            raise DomainError("cantidad no puede ser cero")
        organizacion_politicas.validar_acceso_sucursal(db, usuario_id, sucursal_id)
        tipo_codigo = "ajuste_positivo" if cantidad > 0 else "ajuste_negativo"
        return actualizar_stock_operacion(
            db,
            variante_id=variante_id,
            sucursal_id=sucursal_id,
            tipo_movimiento_codigo=tipo_codigo,
            cantidad=abs(cantidad),
            referencia_tipo="ajuste",
            usuario_id=usuario_id,
            observacion=observacion,
        )

    # -- Transferencias -----------------------------------------------------------

    def crear_transferencia(self, db: Session, datos: TransferenciaCrear, usuario_id: int) -> Transferencia:
        if datos.sucursal_origen_id == datos.sucursal_destino_id:
            raise DomainError("La sucursal de origen y destino no pueden ser la misma")
        organizacion_politicas.obtener_sucursal(db, datos.sucursal_origen_id)
        organizacion_politicas.obtener_sucursal(db, datos.sucursal_destino_id)
        _validar_participa_en_transferencia(db, usuario_id, datos)
        for linea in datos.detalle:
            catalogo_politicas.obtener_variante(db, linea.variante_id)

        if self._transferencias.obtener_por_codigo(db, datos.codigo) is not None:
            raise ConflictoError("Ya existe una transferencia con ese código")

        transferencia = Transferencia(
            codigo=datos.codigo,
            sucursal_origen_id=datos.sucursal_origen_id,
            sucursal_destino_id=datos.sucursal_destino_id,
            estado="pendiente",
            usuario_id=usuario_id,
        )
        transferencia.detalle = [
            TransferenciaDetalle(variante_id=linea.variante_id, cantidad=linea.cantidad) for linea in datos.detalle
        ]
        return self._transferencias.crear(db, transferencia)

    def listar_transferencias(
        self, db: Session, usuario_id: int, sucursal_id: int | None = None
    ) -> list[Transferencia]:
        sucursal_id = organizacion_politicas.acotar_sucursal(db, usuario_id, sucursal_id)
        return self._transferencias.listar(db, sucursal_id)

    def obtener_transferencia(self, db: Session, usuario_id: int, transferencia_id: int) -> Transferencia:
        transferencia = self._transferencias.obtener(db, transferencia_id)
        _validar_participa_en_transferencia(db, usuario_id, transferencia)
        return transferencia

    def enviar_transferencia(self, db: Session, transferencia_id: int, usuario_id: int) -> Transferencia:
        """Genera la salida en la sucursal de origen: un movimiento
        `transferencia_out` por línea, todo en una sola transacción (si una
        línea no tiene stock suficiente, ninguna queda aplicada). La envía el
        personal de la sucursal de origen."""
        transferencia = self._transferencias.obtener(db, transferencia_id)
        organizacion_politicas.validar_acceso_sucursal(db, usuario_id, transferencia.sucursal_origen_id)
        if transferencia.estado != "pendiente":
            raise ConflictoError(f"La transferencia está en estado '{transferencia.estado}', no se puede enviar")

        for linea in transferencia.detalle:
            actualizar_stock_operacion(
                db,
                variante_id=linea.variante_id,
                sucursal_id=transferencia.sucursal_origen_id,
                tipo_movimiento_codigo="transferencia_out",
                cantidad=linea.cantidad,
                referencia_tipo="transferencia",
                referencia_id=transferencia.id,
                usuario_id=usuario_id,
                commit=False,
            )

        transferencia.estado = "en_transito"
        transferencia.fecha_envio = dt.datetime.now(dt.timezone.utc)
        db.commit()
        db.refresh(transferencia)
        return transferencia

    def recibir_transferencia(self, db: Session, transferencia_id: int, usuario_id: int) -> Transferencia:
        """Genera el ingreso en la sucursal de destino usando el costo
        promedio ACTUAL del origen (transferencia_out no lo modifica, así
        que es el mismo costo que tenía la mercadería al salir). La recibe
        el personal de la sucursal de destino."""
        transferencia = self._transferencias.obtener(db, transferencia_id)
        organizacion_politicas.validar_acceso_sucursal(db, usuario_id, transferencia.sucursal_destino_id)
        if transferencia.estado != "en_transito":
            raise ConflictoError(f"La transferencia está en estado '{transferencia.estado}', no se puede recibir")

        for linea in transferencia.detalle:
            stock_origen = self._stock.obtener_por_variante_sucursal(
                db, linea.variante_id, transferencia.sucursal_origen_id
            )
            costo_origen = stock_origen.costo_promedio if stock_origen is not None else Decimal("0")
            actualizar_stock_operacion(
                db,
                variante_id=linea.variante_id,
                sucursal_id=transferencia.sucursal_destino_id,
                tipo_movimiento_codigo="transferencia_in",
                cantidad=linea.cantidad,
                costo_unitario=costo_origen,
                referencia_tipo="transferencia",
                referencia_id=transferencia.id,
                usuario_id=usuario_id,
                commit=False,
            )

        transferencia.estado = "recibida"
        transferencia.fecha_recepcion = dt.datetime.now(dt.timezone.utc)
        db.commit()
        db.refresh(transferencia)
        return transferencia

    def anular_transferencia(self, db: Session, usuario_id: int, transferencia_id: int) -> Transferencia:
        transferencia = self._transferencias.obtener(db, transferencia_id)
        _validar_participa_en_transferencia(db, usuario_id, transferencia)
        if transferencia.estado != "pendiente":
            raise ConflictoError("Solo se puede anular una transferencia pendiente (todavía sin movimientos)")
        transferencia.estado = "anulada"
        db.commit()
        db.refresh(transferencia)
        return transferencia
