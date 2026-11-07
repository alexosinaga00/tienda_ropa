"""CU-09 — Gestionar inventario

Absorbe los antiguos CU-13 (Consultar disponibilidad por sucursal), CU-14
(Consultar inventario global) y CU-15 (Registrar movimiento de inventario).

Actor: Cliente (disponibilidad por sucursal), Administrador y Encargado de
sucursal (inventario y movimientos).
Precondición: la disponibilidad por sucursal es pública; el inventario
requiere el permiso inventario.ver (el encargado solo ve su sucursal; el
alcance global es del administrador, ver plataforma.politicas.acotar_sucursal)
y los movimientos, inventario.gestionar (la sucursal es la del empleado,
salvo alcance global; en una transferencia, la de origen o la de destino
según el paso).
Postcondición: se conoce en qué sucursal hay disponibilidad física de una
variante y las existencias consolidadas (física, reservada, disponible),
las alertas de reposición y la valuación a costo promedio; los ajustes y
transferencias dejan el stock de la sucursal actualizado y el movimiento
registrado en el kardex con usuario, fecha y saldo resultante.

Caso de uso COMPUESTO: la edición de los límites de stock mínimo/máximo se
hace desde la misma pantalla de inventario en vez de tener un caso de uso
propio. El ajuste manual y la transferencia entre sucursales no
reimplementan el cálculo de saldo o de costo promedio: ambos delegan en
catalogo.politicas.actualizar_stock_operacion.
"""

from decimal import Decimal

from sqlalchemy.orm import Session

from app.catalogo import politicas as catalogo_politicas, repository as catalogo_repo
from app.catalogo.models import Stock, MovimientoInventario, Transferencia, TransferenciaDetalle, TipoMovimiento
from app.catalogo.politicas import obtener_stock as _obtener_stock, actualizar_stock_operacion
from app.catalogo.repository import (
    StockRepository,
    MovimientoRepository,
    TipoMovimientoRepository,
    TransferenciaRepository,
)
from app.catalogo.schemas import MovimientoCrear, TransferenciaCrear
from app.core.auditoria import ACCION_AJUSTE, ENTIDAD_MOVIMIENTO_INVENTARIO, ContextoAuditoria
from app.core.exceptions import DomainError, ConflictoError, PermisoDenegadoError
from app.core.tiempo import ahora_utc_naive
from app.plataforma import politicas as plataforma_politicas


# ---- Disponibilidad por sucursal (antiguo CU-13: Consultar disponibilidad por sucursal) ----

class ConsultarDisponibilidadSucursal:
    def __init__(self) -> None:
        self._stock = StockRepository()

    def ejecutar(self, db: Session, variante_id: int, sucursal_id: int | None = None) -> list[Stock]:
        """Sin stock registrado en una sucursal no es un error, es
        simplemente 0 unidades ahí (no se levanta 404)."""
        catalogo_politicas.obtener_variante(db, variante_id)  # 404 si no existe
        stocks = self._stock.listar_por_variante(db, variante_id)
        if sucursal_id is not None:
            stocks = [s for s in stocks if s.sucursal_id == sucursal_id]
        return stocks


# ---- Inventario global (antiguo CU-14: Consultar inventario global) ----

class ConsultarInventarioGlobal:
    def __init__(self) -> None:
        self._stock = StockRepository()

    # Sin sucursal_id, el administrador ve todas y el encargado la suya (la
    # misma regla para consolidado, alertas y valuación, que también usa
    # `inteligencia`, en reportes).

    def listar_consolidado(
        self, db: Session, usuario_id: int, sucursal_id: int | None = None, producto_id: int | None = None
    ) -> list[dict]:
        sucursal_id = plataforma_politicas.acotar_sucursal(db, usuario_id, sucursal_id)
        return catalogo_repo.consolidado(db, sucursal_id, producto_id)

    def listar_alertas(self, db: Session, usuario_id: int, sucursal_id: int | None = None) -> list[dict]:
        sucursal_id = plataforma_politicas.acotar_sucursal(db, usuario_id, sucursal_id)
        return catalogo_repo.alertas(db, sucursal_id)

    def listar_valuacion(self, db: Session, usuario_id: int, sucursal_id: int | None = None) -> list[dict]:
        sucursal_id = plataforma_politicas.acotar_sucursal(db, usuario_id, sucursal_id)
        return catalogo_repo.valuacion(db, sucursal_id)

    def listar_stock_por_sucursal(self, db: Session, usuario_id: int, sucursal_id: int) -> list[Stock]:
        plataforma_politicas.obtener_sucursal(db, sucursal_id)  # 404 si no existe
        plataforma_politicas.validar_acceso_sucursal(db, usuario_id, sucursal_id)
        return self._stock.listar_por_sucursal(db, sucursal_id)

    def listar_stock_por_variante(self, db: Session, usuario_id: int, variante_id: int) -> list[Stock]:
        catalogo_politicas.obtener_variante(db, variante_id)
        stocks = self._stock.listar_por_variante(db, variante_id)
        propia = plataforma_politicas.sucursal_asignada(db, usuario_id)
        return stocks if propia is None else [s for s in stocks if s.sucursal_id == propia]

    def obtener_stock(self, db: Session, usuario_id: int, variante_id: int, sucursal_id: int) -> Stock:
        plataforma_politicas.validar_acceso_sucursal(db, usuario_id, sucursal_id)
        return _obtener_stock(db, variante_id, sucursal_id)

    def actualizar_limites(
        self, db: Session, usuario_id: int, stock_id: int, stock_minimo: int | None, stock_maximo: int | None
    ) -> Stock:
        stock = self._stock.obtener(db, stock_id)
        plataforma_politicas.validar_acceso_sucursal(db, usuario_id, stock.sucursal_id)
        minimo_final = stock_minimo if stock_minimo is not None else stock.stock_minimo
        maximo_final = stock_maximo if stock_maximo is not None else stock.stock_maximo
        if maximo_final is not None and maximo_final < minimo_final:
            raise DomainError("stock_maximo no puede ser menor que stock_minimo")
        return self._stock.actualizar_limites(db, stock, stock_minimo, stock_maximo)


# ---- Movimientos de inventario y transferencias (antiguo CU-15: Registrar movimiento de inventario) ----

def _validar_participa_en_transferencia(db: Session, usuario_id: int, transferencia_o_datos) -> None:
    """Una transferencia la ve y la opera el personal de cualquiera de sus
    dos sucursales (origen o destino); el alcance global, todas."""
    propia = plataforma_politicas.sucursal_asignada(db, usuario_id)
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
        plataforma_politicas.obtener_sucursal(db, sucursal_id)
        plataforma_politicas.validar_acceso_sucursal(db, usuario_id, sucursal_id)
        return self._movimientos.listar_por_variante_sucursal(db, variante_id, sucursal_id)

    # -- Movimientos y ajustes ----------------------------------------------------

    def _confirmar_movimiento(
        self, db: Session, movimiento: MovimientoInventario, tipo_codigo: str, contexto: ContextoAuditoria | None
    ) -> MovimientoInventario:
        """Cierra la transacción del movimiento. Solo los ajustes se auditan
        (los demás tipos ya están en el kardex); la fila de bitácora queda en el
        mismo commit que el movimiento. La observación libre no se copia."""
        if tipo_codigo.startswith("ajuste"):
            plataforma_politicas.registrar_bitacora_de(
                db,
                contexto,
                ENTIDAD_MOVIMIENTO_INVENTARIO,
                movimiento.id,
                ACCION_AJUSTE,
                {
                    "variante_id": movimiento.variante_id,
                    "sucursal_id": movimiento.sucursal_id,
                    "cantidad": movimiento.cantidad,  # con signo: -3 es un faltante
                    "tipo": tipo_codigo,
                },
            )
        db.commit()
        db.refresh(movimiento)
        return movimiento

    def registrar_movimiento(
        self, db: Session, usuario_id: int, datos: MovimientoCrear, contexto: ContextoAuditoria | None = None
    ) -> MovimientoInventario:
        """POST /inventario/movimientos. Antes el router llamaba directo a
        actualizar_stock_operacion (regla 5); acá además se valida que la
        sucursal sea la del empleado."""
        plataforma_politicas.validar_acceso_sucursal(db, usuario_id, datos.sucursal_id)
        movimiento = actualizar_stock_operacion(
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
            commit=False,
        )
        return self._confirmar_movimiento(db, movimiento, datos.tipo_movimiento_codigo, contexto)

    def registrar_ajuste(
        self,
        db: Session,
        variante_id: int,
        sucursal_id: int,
        cantidad: int,
        usuario_id: int,
        observacion: str | None,
        contexto: ContextoAuditoria | None = None,
    ) -> MovimientoInventario:
        """Envoltorio delgado sobre actualizar_stock_operacion(): traduce el
        signo de `cantidad` (positivo = sobrante, negativo = faltante) al
        tipo de movimiento correspondiente."""
        if cantidad == 0:
            raise DomainError("cantidad no puede ser cero")
        plataforma_politicas.validar_acceso_sucursal(db, usuario_id, sucursal_id)
        tipo_codigo = "ajuste_positivo" if cantidad > 0 else "ajuste_negativo"
        movimiento = actualizar_stock_operacion(
            db,
            variante_id=variante_id,
            sucursal_id=sucursal_id,
            tipo_movimiento_codigo=tipo_codigo,
            cantidad=abs(cantidad),
            referencia_tipo="ajuste",
            usuario_id=usuario_id,
            observacion=observacion,
            commit=False,
        )
        return self._confirmar_movimiento(db, movimiento, tipo_codigo, contexto)

    # -- Transferencias -----------------------------------------------------------

    def crear_transferencia(self, db: Session, datos: TransferenciaCrear, usuario_id: int) -> Transferencia:
        if datos.sucursal_origen_id == datos.sucursal_destino_id:
            raise DomainError("La sucursal de origen y destino no pueden ser la misma")
        plataforma_politicas.obtener_sucursal(db, datos.sucursal_origen_id)
        plataforma_politicas.obtener_sucursal(db, datos.sucursal_destino_id)
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
        sucursal_id = plataforma_politicas.acotar_sucursal(db, usuario_id, sucursal_id)
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
        # Fila bloqueada ANTES de validar el estado: dos envíos simultáneos no
        # pasan ambos el chequeo.
        transferencia = self._transferencias.obtener_bloqueado(db, transferencia_id)
        plataforma_politicas.validar_acceso_sucursal(db, usuario_id, transferencia.sucursal_origen_id)
        if transferencia.estado != "pendiente":
            raise ConflictoError(f"La transferencia está en estado '{transferencia.estado}', no se puede enviar")

        catalogo_politicas.bloquear_stock_en_orden(
            db, [(linea.variante_id, transferencia.sucursal_origen_id) for linea in transferencia.detalle]
        )
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
        transferencia.fecha_envio = ahora_utc_naive()
        db.commit()
        db.refresh(transferencia)
        return transferencia

    def recibir_transferencia(self, db: Session, transferencia_id: int, usuario_id: int) -> Transferencia:
        """Genera el ingreso en la sucursal de destino usando el costo
        promedio ACTUAL del origen (transferencia_out no lo modifica, así
        que es el mismo costo que tenía la mercadería al salir). La recibe
        el personal de la sucursal de destino."""
        # Fila bloqueada ANTES de validar el estado (ver enviar_transferencia).
        transferencia = self._transferencias.obtener_bloqueado(db, transferencia_id)
        plataforma_politicas.validar_acceso_sucursal(db, usuario_id, transferencia.sucursal_destino_id)
        if transferencia.estado != "en_transito":
            raise ConflictoError(f"La transferencia está en estado '{transferencia.estado}', no se puede recibir")

        catalogo_politicas.bloquear_stock_en_orden(
            db, [(linea.variante_id, transferencia.sucursal_destino_id) for linea in transferencia.detalle]
        )
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
        transferencia.fecha_recepcion = ahora_utc_naive()
        db.commit()
        db.refresh(transferencia)
        return transferencia

    def anular_transferencia(self, db: Session, usuario_id: int, transferencia_id: int) -> Transferencia:
        # Bloqueada: no compite con un envío simultáneo de la misma transferencia.
        transferencia = self._transferencias.obtener_bloqueado(db, transferencia_id)
        _validar_participa_en_transferencia(db, usuario_id, transferencia)
        if transferencia.estado != "pendiente":
            raise ConflictoError("Solo se puede anular una transferencia pendiente (todavía sin movimientos)")
        transferencia.estado = "anulada"
        db.commit()
        db.refresh(transferencia)
        return transferencia
