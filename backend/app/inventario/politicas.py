"""Corazón del paquete `inventario`: actualizar_stock_operacion() es la
operación atómica compartida (kardex + costeo promedio ponderado) que usan
CU-12 (abastecimiento), CU-15, CU-24 y CU-25 (ventas) y CU-40 (devolución).
reservar_stock()/liberar_stock() manejan la cantidad_reservada sin nunca
generar un movimiento ni tocar cantidad_fisica.

Ninguna de las tres es un caso de uso del catálogo: son la lógica interna
que evita que cada caso de uso reimplemente el cálculo del promedio
ponderado o el manejo de reservas.
"""

import datetime as dt
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session

from app.catalogo import politicas as catalogo_politicas
from app.core.exceptions import ConflictoError, DomainError, NoEncontradoError
from app.inventario.models import MovimientoInventario, Stock
from app.inventario.repository import MovimientoRepository, StockRepository, TipoMovimientoRepository
from app.organizacion import politicas as organizacion_politicas

stock_repo = StockRepository()
movimiento_repo = MovimientoRepository()
tipo_movimiento_repo = TipoMovimientoRepository()

_CUATRO_DECIMALES = Decimal("0.0001")


def actualizar_stock_operacion(
    db: Session,
    *,
    variante_id: int,
    sucursal_id: int,
    tipo_movimiento_codigo: str,
    cantidad: int,
    costo_unitario: Decimal | None = None,
    referencia_tipo: str | None = None,
    referencia_id: int | None = None,
    usuario_id: int | None = None,
    observacion: str | None = None,
    commit: bool = True,
) -> MovimientoInventario:
    """`commit=False` lo usan operaciones de otros paquetes que registran
    varios movimientos como una sola transacción (p. ej.
    abastecimiento.crear_recepcion con varias líneas, o
    enviar_transferencia/recibir_transferencia de CU-15): si una línea
    falla, ninguna de las anteriores debe quedar aplicada. Quien pasa
    `commit=False` es responsable de hacer `db.commit()` al final."""
    if cantidad <= 0:
        raise DomainError("cantidad debe ser positiva")

    catalogo_politicas.obtener_variante(db, variante_id)  # 404 si no existe
    organizacion_politicas.obtener_sucursal(db, sucursal_id)  # 404 si no existe

    tipo = tipo_movimiento_repo.obtener_por_codigo(db, tipo_movimiento_codigo)

    if tipo.afecta_costo and costo_unitario is None:
        raise DomainError(f"El tipo de movimiento '{tipo.codigo}' requiere costo_unitario")

    # Bloquea la fila de stock (SELECT FOR UPDATE en Postgres) para que dos
    # movimientos concurrentes sobre la misma variante+sucursal no pisen el
    # saldo el uno al otro.
    stock = stock_repo.obtener_o_crear_bloqueado(db, variante_id, sucursal_id)

    cantidad_firmada = cantidad * tipo.signo
    stock_anterior = stock.cantidad_fisica
    nueva_cantidad_fisica = stock_anterior + cantidad_firmada

    if nueva_cantidad_fisica < 0:
        raise ConflictoError("El movimiento dejaría el stock físico en negativo")
    if nueva_cantidad_fisica < stock.cantidad_reservada:
        raise ConflictoError("El movimiento dejaría stock reservado sin respaldo físico")

    # Si el tipo afecta el costo (siempre una entrada: no tiene sentido
    # recalcular el promedio con una salida), recalcula el promedio
    # ponderado con la cantidad y el costo de ESTE ingreso.
    if tipo.afecta_costo and tipo.signo > 0:
        costo_anterior = stock.costo_promedio
        promedio_exacto = (
            Decimal(stock_anterior) * costo_anterior + Decimal(cantidad) * costo_unitario
        ) / Decimal(stock_anterior + cantidad)
        # NUMERIC(12,4) en la base: se redondea acá para que el valor que
        # ve el código sea el mismo que va a quedar persistido.
        nuevo_promedio = promedio_exacto.quantize(_CUATRO_DECIMALES, rounding=ROUND_HALF_UP)
    else:
        nuevo_promedio = stock.costo_promedio

    # Actualiza stock.cantidad_fisica y costo_promedio.
    stock.cantidad_fisica = nueva_cantidad_fisica
    stock.costo_promedio = nuevo_promedio

    # Inserta el movimiento con su saldo_post y costo_promedio_post.
    movimiento = MovimientoInventario(
        variante_id=variante_id,
        sucursal_id=sucursal_id,
        tipo_movimiento_id=tipo.id,
        cantidad=cantidad_firmada,
        costo_unitario=costo_unitario,
        costo_promedio_post=nuevo_promedio if tipo.afecta_costo else None,
        saldo_post=nueva_cantidad_fisica,
        referencia_tipo=referencia_tipo,
        referencia_id=referencia_id,
        usuario_id=usuario_id,
        observacion=observacion,
    )
    movimiento_repo.crear(db, movimiento)

    if commit:
        db.commit()
    else:
        db.flush()
    db.refresh(movimiento)
    return movimiento


def reservar_stock(
    db: Session, variante_id: int, sucursal_id: int, cantidad: int, commit: bool = True
) -> Stock:
    """Incrementa cantidad_reservada. Nunca toca cantidad_fisica ni genera
    movimiento de inventario. `commit=False`: ver el comentario en
    actualizar_stock_operacion (lo usa reservas.CU-16, que reserva varias
    líneas como una sola transacción)."""
    if cantidad <= 0:
        raise DomainError("cantidad debe ser positiva")

    catalogo_politicas.obtener_variante(db, variante_id)
    organizacion_politicas.obtener_sucursal(db, sucursal_id)

    stock = stock_repo.obtener_o_crear_bloqueado(db, variante_id, sucursal_id)
    disponible = stock.cantidad_fisica - stock.cantidad_reservada
    if cantidad > disponible:
        raise ConflictoError("No hay stock disponible suficiente para reservar")

    stock.cantidad_reservada += cantidad
    if commit:
        db.commit()
    else:
        db.flush()
    db.refresh(stock)
    return stock


def liberar_stock(
    db: Session, variante_id: int, sucursal_id: int, cantidad: int, commit: bool = True
) -> Stock:
    """Decrementa cantidad_reservada. Nunca toca cantidad_fisica ni genera
    movimiento de inventario. `commit=False`: ver el comentario en
    actualizar_stock_operacion."""
    if cantidad <= 0:
        raise DomainError("cantidad debe ser positiva")

    stock = stock_repo.obtener_o_crear_bloqueado(db, variante_id, sucursal_id)
    if cantidad > stock.cantidad_reservada:
        raise ConflictoError("No se puede liberar más de lo reservado")

    stock.cantidad_reservada -= cantidad
    if commit:
        db.commit()
    else:
        db.flush()
    db.refresh(stock)
    return stock


def obtener_stock(db: Session, variante_id: int, sucursal_id: int) -> Stock:
    """Para que `ventas` lea el costo_promedio actual antes de congelarlo en
    el detalle de la venta, sin consultar `stock` directamente."""
    stock = stock_repo.obtener_por_variante_sucursal(db, variante_id, sucursal_id)
    if stock is None:
        raise NoEncontradoError("Todavía no hay stock registrado para esa variante en esa sucursal")
    return stock


def listar_variantes_con_stock(db: Session, sucursal_id: int | None = None) -> set[int]:
    """Para `inteligencia` (capa de reglas del recomendador) y `catalogo`
    (CU-10, filtro `solo_disponibles`): variantes con stock disponible, en
    cualquier sucursal si no se pasa `sucursal_id` o en esa sola si se
    pasa, sin consultar `stock` directamente."""
    return stock_repo.listar_variantes_con_stock(db, sucursal_id)
