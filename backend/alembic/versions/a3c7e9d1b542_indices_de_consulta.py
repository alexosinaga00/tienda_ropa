"""Indices para las consultas mas frecuentes (pantalla de inicio, Caja, Mis compras, webhook de pagos)

Solo agrega indices: sin columnas, sin tablas y sin tocar datos. Cada uno cubre una consulta que hoy recorre la tabla entera:
- venta (empresa_id, sucursal_id, fecha): las ventas de una sucursal en un rango de fechas (pantalla de inicio, Caja).
  Las de toda la empresa ya las cubre `ix_venta_empresa_fecha`.
- venta (cliente_id): "Mis compras" de un cliente.
- venta_detalle (venta_id), pago (venta_id), devolucion (venta_id), devolucion_detalle (devolucion_id): traer las lineas, los pagos y lo
  devuelto de una venta (las llaves foraneas de Postgres NO crean indice por si solas).
- reserva (empresa_id, sucursal_id, fecha_visita): las reservas de una sucursal en un dia.
- notificacion (usuario_id, creado_en): los avisos de un usuario, los mas recientes primero.
- movimiento_inventario (variante_id, sucursal_id): el kardex de una variante en una sucursal.
- transaccion_pasarela (pasarela, id_transaccion): el webhook y la pantalla QR buscan la transaccion SOLO por esos dos datos,
  sin conocer la empresa (por eso no sirve el indice por empresa).

Revisada a mano. Los nombres coinciden con los de `Index(...)` en los modelos (compare_metadata no debe ver diferencias).
En una base grande conviene crearlos con CREATE INDEX CONCURRENTLY; aqui las tablas son chicas y el bloqueo dura un instante.
No importa nada de `app.*`.

Revision ID: a3c7e9d1b542
Revises: b6d1f3a8c725
Create Date: 2026-11-07 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a3c7e9d1b542'
down_revision: Union[str, None] = 'b6d1f3a8c725'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (nombre, tabla, columnas)
INDICES = (
    ('ix_venta_empresa_sucursal_fecha', 'venta', ['empresa_id', 'sucursal_id', 'fecha']),
    ('ix_venta_cliente', 'venta', ['cliente_id']),
    ('ix_venta_detalle_venta', 'venta_detalle', ['venta_id']),
    ('ix_pago_venta', 'pago', ['venta_id']),
    ('ix_devolucion_venta', 'devolucion', ['venta_id']),
    ('ix_devolucion_detalle_devolucion', 'devolucion_detalle', ['devolucion_id']),
    ('ix_reserva_empresa_sucursal_visita', 'reserva', ['empresa_id', 'sucursal_id', 'fecha_visita']),
    ('ix_notificacion_usuario', 'notificacion', ['usuario_id', 'creado_en']),
    ('ix_movimiento_inventario_variante_sucursal', 'movimiento_inventario', ['variante_id', 'sucursal_id']),
    ('ix_transaccion_pasarela_referencia', 'transaccion_pasarela', ['pasarela', 'id_transaccion']),
)


def upgrade() -> None:
    for nombre, tabla, columnas in INDICES:
        op.create_index(nombre, tabla, columnas)


def downgrade() -> None:
    for nombre, tabla, _columnas in reversed(INDICES):
        op.drop_index(nombre, table_name=tabla)
