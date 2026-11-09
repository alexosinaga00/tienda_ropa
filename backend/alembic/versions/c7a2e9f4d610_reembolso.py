"""reembolso: el dinero que se le devuelve a quien compró

Tabla `reembolso` (CU-17 y CU-18): una fila por cada devolución de dinero, sea de una devolución sin cambio de prenda o de
anular un pago. Guarda el método del pago original, el monto en bolivianos (y en dólares si la pasarela cobró en dólares),
el estado (`pendiente` / `reembolsado` / `fallido`) y la referencia de la pasarela. El cierre de caja resta de cada turno los
reembolsos en efectivo cuyo `completado_en` cae dentro de su ventana, por eso el índice `ix_reembolso_caja`.

Revisada a mano: solo `create_table` + 4 índices. No toca otras tablas. No importa nada de `app.*`.

Revision ID: c7a2e9f4d610
Revises: b8d4f1a7c935
Create Date: 2026-11-08 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c7a2e9f4d610'
down_revision: Union[str, None] = 'b8d4f1a7c935'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'reembolso',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('empresa_id', sa.Integer(), nullable=False),
        sa.Column('devolucion_id', sa.Integer(), nullable=True),
        sa.Column('pago_id', sa.Integer(), nullable=False),
        sa.Column('venta_id', sa.Integer(), nullable=False),
        sa.Column('sucursal_id', sa.Integer(), nullable=False),
        sa.Column('metodo', sa.String(length=25), nullable=False),
        sa.Column('monto', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('monto_usd', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('estado', sa.String(length=15), nullable=False),
        sa.Column('referencia_externa', sa.String(length=120), nullable=True),
        sa.Column('motivo_fallo', sa.String(length=60), nullable=True),
        sa.Column('usuario_id', sa.Integer(), nullable=False),
        sa.Column('creado_en', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('completado_en', sa.DateTime(), nullable=True),
        sa.CheckConstraint('monto > 0', name='ck_reembolso_monto'),
        sa.CheckConstraint("estado IN ('pendiente','reembolsado','fallido')", name='ck_reembolso_estado'),
        sa.ForeignKeyConstraint(['empresa_id'], ['empresa.id']),
        sa.ForeignKeyConstraint(['devolucion_id'], ['devolucion.id']),
        sa.ForeignKeyConstraint(['pago_id'], ['pago.id']),
        sa.ForeignKeyConstraint(['venta_id'], ['venta.id']),
        sa.ForeignKeyConstraint(['sucursal_id'], ['sucursal.id']),
        sa.ForeignKeyConstraint(['usuario_id'], ['usuario.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_reembolso_empresa_id', 'reembolso', ['empresa_id'], unique=False)
    op.create_index('ix_reembolso_pago', 'reembolso', ['pago_id'], unique=False)
    op.create_index('ix_reembolso_venta', 'reembolso', ['venta_id'], unique=False)
    op.create_index(
        'ix_reembolso_caja', 'reembolso', ['empresa_id', 'sucursal_id', 'metodo', 'completado_en'], unique=False
    )


def downgrade() -> None:
    op.drop_index('ix_reembolso_caja', table_name='reembolso')
    op.drop_index('ix_reembolso_venta', table_name='reembolso')
    op.drop_index('ix_reembolso_pago', table_name='reembolso')
    op.drop_index('ix_reembolso_empresa_id', table_name='reembolso')
    op.drop_table('reembolso')
