"""contratacion de planes: precio del plan, suscripcion de prueba y pedido_contratacion

Fase 1 de la contratacion de planes desde la portada publica:
- `plan.precio_mensual_bs` Numeric(10,2) NULL con CHECK (>= 0). El anual (20 % menos) no lleva columna.
  Precios iniciales de los planes que existan: basico 120, estandar 290 y profesional 590 (Bs por mes).
- `suscripcion.es_prueba` Boolean NOT NULL, por defecto falso (las suscripciones actuales quedan en falso).
- Tabla global `pedido_contratacion` (compra o prueba gratuita ANTES de que exista la empresa): SIN
  `empresa_id`, la empresa creada se enlaza en `empresa_creada_id`. Guarda el hash bcrypt de la contrasena
  del administrador, nunca la contrasena. Indice unico parcial: una sola prueba gratuita viva por correo.

Revisada a mano: dos columnas, un UPDATE de precios y `create_table` con sus indices. No importa nada de
`app.*`.

Revision ID: c5e1b7a38d92
Revises: a9d3f5c27e84
Create Date: 2026-11-03 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c5e1b7a38d92'
down_revision: Union[str, None] = 'a9d3f5c27e84'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Bs por mes. Solo se actualizan los planes que existan (el Estandar es un dato de demostracion).
PRECIOS_INICIALES = (
    ('basico', 120),
    ('estandar', 290),
    ('profesional', 590),
)

CONDICION_PRUEBA_VIVA = "tipo = 'prueba' AND estado NOT IN ('cancelado','vencido','fallido')"


def upgrade() -> None:
    op.add_column('plan', sa.Column('precio_mensual_bs', sa.Numeric(precision=10, scale=2), nullable=True))
    op.create_check_constraint(
        'ck_plan_precio_mensual',
        'plan',
        'precio_mensual_bs IS NULL OR precio_mensual_bs >= 0',
    )
    for codigo, precio in PRECIOS_INICIALES:
        op.execute(
            sa.text("UPDATE plan SET precio_mensual_bs = :precio WHERE codigo = :codigo").bindparams(
                precio=precio, codigo=codigo
            )
        )

    op.add_column(
        'suscripcion',
        sa.Column('es_prueba', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    )

    op.create_table(
        'pedido_contratacion',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('token', sa.String(length=64), nullable=False),
        sa.Column('tipo', sa.String(length=10), nullable=False),
        sa.Column('periodo', sa.String(length=10), nullable=True),
        sa.Column('plan_id', sa.Integer(), nullable=False),
        sa.Column('empresa_nombre', sa.String(length=120), nullable=False),
        sa.Column('empresa_codigo', sa.String(length=60), nullable=False),
        sa.Column('admin_nombre', sa.String(length=60), nullable=False),
        sa.Column('admin_apellido', sa.String(length=60), nullable=False),
        sa.Column('admin_email', sa.String(length=120), nullable=False),
        sa.Column('admin_telefono', sa.String(length=20), nullable=True),
        sa.Column('admin_password_hash', sa.String(length=255), nullable=False),
        sa.Column('estado', sa.String(length=20), server_default='pendiente', nullable=False),
        sa.Column('monto_bs', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('monto_usd', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('tipo_cambio', sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column('paypal_order_id', sa.String(length=64), nullable=True),
        sa.Column('empresa_creada_id', sa.Integer(), nullable=True),
        sa.Column('ip', sa.String(length=45), nullable=True),
        sa.Column('expira_en', sa.DateTime(), nullable=True),
        sa.Column('creado_en', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('actualizado_en', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("tipo IN ('pago','prueba')", name='ck_pedido_contratacion_tipo'),
        sa.CheckConstraint("periodo IS NULL OR periodo IN ('mensual','anual')", name='ck_pedido_contratacion_periodo'),
        sa.CheckConstraint(
            "estado IN ('pendiente','pagado','pagado_sin_empresa','completado','cancelado','vencido','fallido')",
            name='ck_pedido_contratacion_estado',
        ),
        sa.ForeignKeyConstraint(['plan_id'], ['plan.id']),
        sa.ForeignKeyConstraint(['empresa_creada_id'], ['empresa.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token'),
        sa.UniqueConstraint('paypal_order_id'),
    )
    op.create_index(
        'ux_pedido_prueba_correo',
        'pedido_contratacion',
        ['admin_email'],
        unique=True,
        postgresql_where=sa.text(CONDICION_PRUEBA_VIVA),
        sqlite_where=sa.text(CONDICION_PRUEBA_VIVA),
    )
    op.create_index(
        'ix_pedido_contratacion_estado_creado', 'pedido_contratacion', ['estado', 'creado_en'], unique=False
    )


def downgrade() -> None:
    op.drop_index('ix_pedido_contratacion_estado_creado', table_name='pedido_contratacion')
    op.drop_index(
        'ux_pedido_prueba_correo',
        table_name='pedido_contratacion',
        postgresql_where=sa.text(CONDICION_PRUEBA_VIVA),
        sqlite_where=sa.text(CONDICION_PRUEBA_VIVA),
    )
    op.drop_table('pedido_contratacion')
    op.drop_column('suscripcion', 'es_prueba')
    op.drop_constraint('ck_plan_precio_mensual', 'plan', type_='check')
    op.drop_column('plan', 'precio_mensual_bs')
