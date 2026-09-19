"""CU-12 — Registrar recepción de mercadería

Actor: Administrador.
Precondición: sesión con el permiso abastecimiento.gestionar; el
proveedor (CU-11), la sucursal y las variantes existen.
Postcondición: el stock físico de la sucursal aumenta, el costo promedio
queda actualizado y la recepción queda trazada en el kardex.

`GestionarOrdenesCompra`, en este mismo archivo, no es un caso de uso del
catálogo de 43: es una entidad de soporte (ver CLAUDE.md, nota sobre
entidades de soporte) que CU-12 referencia de forma opcional al recibir
mercadería, y a la que actualiza el estado cuando corresponde.
"""

from decimal import Decimal

from sqlalchemy.orm import Session

from app.abastecimiento.models import OrdenCompra, OrdenCompraDetalle, Recepcion, RecepcionDetalle
from app.abastecimiento.repository import OrdenCompraRepository, ProveedorRepository, RecepcionRepository
from app.abastecimiento.schemas import OrdenCompraActualizar, OrdenCompraCrear, RecepcionCrear
from app.catalogo import politicas as catalogo_politicas
from app.core.exceptions import ConflictoError, DomainError
from app.inventario.politicas import actualizar_stock_operacion
from app.organizacion import politicas as organizacion_politicas


class GestionarOrdenesCompra:
    """Entidad de soporte, sin CU propio: ver docstring del módulo."""

    def __init__(self) -> None:
        self._ordenes = OrdenCompraRepository()
        self._proveedores = ProveedorRepository()

    def crear(self, db: Session, datos: OrdenCompraCrear, creado_por: int | None) -> OrdenCompra:
        self._proveedores.obtener(db, datos.proveedor_id)  # 404 si no existe / está inactivo
        organizacion_politicas.obtener_sucursal(db, datos.sucursal_id)
        for linea in datos.detalle:
            catalogo_politicas.obtener_variante(db, linea.variante_id)

        if self._ordenes.obtener_por_codigo(db, datos.codigo) is not None:
            raise ConflictoError("Ya existe una orden de compra con ese código")

        total = sum((Decimal(linea.cantidad) * linea.costo_unitario for linea in datos.detalle), Decimal("0"))
        orden = OrdenCompra(
            codigo=datos.codigo,
            proveedor_id=datos.proveedor_id,
            sucursal_id=datos.sucursal_id,
            fecha_esperada=datos.fecha_esperada,
            estado="borrador",
            total=total,
            creado_por=creado_por,
        )
        orden.detalle = [
            OrdenCompraDetalle(variante_id=linea.variante_id, cantidad=linea.cantidad, costo_unitario=linea.costo_unitario)
            for linea in datos.detalle
        ]
        return self._ordenes.crear(db, orden)

    def actualizar(self, db: Session, orden_id: int, datos: OrdenCompraActualizar) -> OrdenCompra:
        orden = self._ordenes.obtener(db, orden_id)
        if orden.estado != "borrador":
            raise ConflictoError("Solo se puede editar una orden de compra en estado 'borrador'")

        if datos.proveedor_id is not None:
            self._proveedores.obtener(db, datos.proveedor_id)
            orden.proveedor_id = datos.proveedor_id
        if datos.sucursal_id is not None:
            organizacion_politicas.obtener_sucursal(db, datos.sucursal_id)
            orden.sucursal_id = datos.sucursal_id
        if datos.fecha_esperada is not None:
            orden.fecha_esperada = datos.fecha_esperada

        if datos.detalle is not None:
            for linea in datos.detalle:
                catalogo_politicas.obtener_variante(db, linea.variante_id)
            nuevas_lineas = [
                OrdenCompraDetalle(variante_id=linea.variante_id, cantidad=linea.cantidad, costo_unitario=linea.costo_unitario)
                for linea in datos.detalle
            ]
            return self._ordenes.reemplazar_detalle(db, orden, nuevas_lineas)

        return self._ordenes.guardar(db, orden)

    def enviar(self, db: Session, orden_id: int) -> OrdenCompra:
        orden = self._ordenes.obtener(db, orden_id)
        if orden.estado != "borrador":
            raise ConflictoError(f"La orden está en estado '{orden.estado}', no se puede enviar")
        orden.estado = "enviada"
        return self._ordenes.guardar(db, orden)

    def anular(self, db: Session, orden_id: int) -> OrdenCompra:
        orden = self._ordenes.obtener(db, orden_id)
        if orden.estado not in ("borrador", "enviada"):
            raise ConflictoError("Solo se puede anular una orden en 'borrador' o 'enviada'")
        orden.estado = "anulada"
        return self._ordenes.guardar(db, orden)

    def listar(self, db: Session, proveedor_id: int | None = None, sucursal_id: int | None = None) -> list[OrdenCompra]:
        return self._ordenes.listar(db, proveedor_id, sucursal_id)

    def obtener(self, db: Session, orden_id: int) -> OrdenCompra:
        return self._ordenes.obtener(db, orden_id)


class RegistrarRecepcionMercaderia:
    def __init__(self) -> None:
        self._proveedores = ProveedorRepository()
        self._ordenes = OrdenCompraRepository()
        self._recepciones = RecepcionRepository()
        self.ordenes_compra = GestionarOrdenesCompra()

    def _actualizar_estado_orden_por_recepciones(self, db: Session, orden: OrdenCompra) -> None:
        recibido_por_variante = self._recepciones.total_recibido_por_variante(db, orden.id)
        completa = all(recibido_por_variante.get(linea.variante_id, 0) >= linea.cantidad for linea in orden.detalle)
        algo_recibido = any(recibido_por_variante.get(linea.variante_id, 0) > 0 for linea in orden.detalle)
        if completa:
            orden.estado = "recibida"
        elif algo_recibido:
            orden.estado = "parcial"

    def registrar(
        self, db: Session, datos: RecepcionCrear, empleado_id: int | None, creado_por: int | None
    ) -> Recepcion:
        self._proveedores.obtener(db, datos.proveedor_id)  # 404 si no existe / está inactivo
        organizacion_politicas.obtener_sucursal(db, datos.sucursal_id)

        orden = None
        if datos.orden_compra_id is not None:
            orden = self._ordenes.obtener(db, datos.orden_compra_id)
            if orden.estado not in ("enviada", "parcial"):
                raise DomainError(f"La orden de compra está en estado '{orden.estado}', no admite recepciones")

        if self._recepciones.obtener_por_codigo(db, datos.codigo) is not None:
            raise ConflictoError("Ya existe una recepción con ese código")

        recepcion = Recepcion(
            codigo=datos.codigo,
            orden_compra_id=datos.orden_compra_id,
            proveedor_id=datos.proveedor_id,
            sucursal_id=datos.sucursal_id,
            empleado_id=empleado_id,
            observacion=datos.observacion,
        )
        self._recepciones.crear(db, recepcion)  # flush: recepcion.id ya queda disponible

        for linea in datos.detalle:
            catalogo_politicas.obtener_variante(db, linea.variante_id)  # 404 si no existe
            db.add(
                RecepcionDetalle(
                    recepcion_id=recepcion.id,
                    variante_id=linea.variante_id,
                    cantidad=linea.cantidad,
                    costo_unitario=linea.costo_unitario,
                )
            )
            # commit=False: toda la recepción (cabecera + detalle + los N
            # movimientos que genera) es UNA sola transacción. Si una línea
            # falla (p. ej. tipo de movimiento inválido), no queda nada aplicado.
            actualizar_stock_operacion(
                db,
                variante_id=linea.variante_id,
                sucursal_id=datos.sucursal_id,
                tipo_movimiento_codigo="recepcion",
                cantidad=linea.cantidad,
                costo_unitario=linea.costo_unitario,
                referencia_tipo="recepcion",
                referencia_id=recepcion.id,
                usuario_id=creado_por,
                commit=False,
            )

        db.flush()
        if orden is not None:
            self._actualizar_estado_orden_por_recepciones(db, orden)

        db.commit()
        db.refresh(recepcion)
        return recepcion

    def listar(self, db: Session, orden_compra_id: int | None = None) -> list[Recepcion]:
        return self._recepciones.listar(db, orden_compra_id)

    def obtener(self, db: Session, recepcion_id: int) -> Recepcion:
        return self._recepciones.obtener(db, recepcion_id)
