"""PayPal guardado del cliente y pedido sin conexion (CU-18 y CU-13)

Dos tablas nuevas, ambas de una empresa (`empresa_id` NOT NULL):

- `metodo_pago_guardado`: el PayPal que un cliente autorizo UNA vez, con conexion, para que el servidor le cobre despues
  (PayPal Vault v3). Guarda el setup token, el payment token (`vault_id`) y el correo de PayPal ya ENMASCARADO; nunca
  datos de tarjeta. Estados `pendiente`, `activo` y `revocado`; un indice unico parcial deja UN solo `activo` por
  usuario. Queda fuera de las copias de seguridad (guarda un token de pago).
- `pedido_diferido`: el resultado FINAL de un pedido armado sin conexion y cobrado al reconectar. UNIQUE (empresa_id,
  operacion_id) hace idempotente el reenvio. `en_proceso` es un estado interno que nunca llega a confirmarse.

Revisada a mano: solo `create_table` y sus indices. No toca otras tablas ni permisos (las rutas usan `ventas.digital`).
No importa nada de `app.*`.

Revision ID: e7a3c91d5b28
Revises: d2f8a6c14b97
Create Date: 2026-11-06 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e7a3c91d5b28'
down_revision: Union[str, None] = 'd2f8a6c14b97'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CONDICION_ACTIVO = "estado = 'activo'"


def upgrade() -> None:
    op.create_table(
        'metodo_pago_guardado',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('empresa_id', sa.Integer(), nullable=False),
        sa.Column('usuario_id', sa.Integer(), nullable=False),
        sa.Column('proveedor', sa.String(length=20), nullable=False),
        sa.Column('estado', sa.String(length=15), nullable=False),
        sa.Column('setup_token_id', sa.String(length=255), nullable=False),
        sa.Column('payment_token_id', sa.String(length=255), nullable=True),
        sa.Column('correo_paypal', sa.String(length=120), nullable=True),
        sa.Column('creado_en', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('confirmado_en', sa.DateTime(), nullable=True),
        sa.Column('revocado_en', sa.DateTime(), nullable=True),
        sa.CheckConstraint("proveedor IN ('paypal')", name='ck_metodo_pago_guardado_proveedor'),
        sa.CheckConstraint("estado IN ('pendiente','activo','revocado')", name='ck_metodo_pago_guardado_estado'),
        sa.ForeignKeyConstraint(['empresa_id'], ['empresa.id']),
        sa.ForeignKeyConstraint(['usuario_id'], ['usuario.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_metodo_pago_guardado_empresa_id', 'metodo_pago_guardado', ['empresa_id'], unique=False)
    op.create_index('ix_metodo_pago_guardado_usuario', 'metodo_pago_guardado', ['usuario_id', 'estado'], unique=False)
    op.create_index(
        'ux_metodo_pago_guardado_activo',
        'metodo_pago_guardado',
        ['usuario_id'],
        unique=True,
        postgresql_where=sa.text(CONDICION_ACTIVO),
        sqlite_where=sa.text(CONDICION_ACTIVO),
    )
    op.create_index(
        'ux_metodo_pago_guardado_setup', 'metodo_pago_guardado', ['empresa_id', 'setup_token_id'], unique=True
    )

    op.create_table(
        'pedido_diferido',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('empresa_id', sa.Integer(), nullable=False),
        sa.Column('operacion_id', sa.Uuid(), nullable=False),
        sa.Column('usuario_id', sa.Integer(), nullable=False),
        sa.Column('sucursal_id', sa.Integer(), nullable=False),
        sa.Column('estado', sa.String(length=15), nullable=False),
        sa.Column('motivo', sa.String(length=40), nullable=True),
        sa.Column('mensaje', sa.String(length=300), nullable=True),
        sa.Column('venta_id', sa.Integer(), nullable=True),
        sa.Column('total', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('total_usd', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('creado_en', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("estado IN ('en_proceso','cobrado','rechazado')", name='ck_pedido_diferido_estado'),
        sa.ForeignKeyConstraint(['empresa_id'], ['empresa.id']),
        sa.ForeignKeyConstraint(['usuario_id'], ['usuario.id']),
        sa.ForeignKeyConstraint(['sucursal_id'], ['sucursal.id']),
        sa.ForeignKeyConstraint(['venta_id'], ['venta.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('empresa_id', 'operacion_id', name='uq_pedido_diferido_empresa_operacion'),
    )
    op.create_index('ix_pedido_diferido_empresa_id', 'pedido_diferido', ['empresa_id'], unique=False)
    op.create_index('ix_pedido_diferido_usuario', 'pedido_diferido', ['usuario_id', 'creado_en'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_pedido_diferido_usuario', table_name='pedido_diferido')
    op.drop_index('ix_pedido_diferido_empresa_id', table_name='pedido_diferido')
    op.drop_table('pedido_diferido')
    op.drop_index('ux_metodo_pago_guardado_setup', table_name='metodo_pago_guardado')
    op.drop_index(
        'ux_metodo_pago_guardado_activo',
        table_name='metodo_pago_guardado',
        postgresql_where=sa.text(CONDICION_ACTIVO),
        sqlite_where=sa.text(CONDICION_ACTIVO),
    )
    op.drop_index('ix_metodo_pago_guardado_usuario', table_name='metodo_pago_guardado')
    op.drop_index('ix_metodo_pago_guardado_empresa_id', table_name='metodo_pago_guardado')
    op.drop_table('metodo_pago_guardado')
