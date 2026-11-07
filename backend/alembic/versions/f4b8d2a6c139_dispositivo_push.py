"""Dispositivos de notificaciones push (FCM)

Una tabla nueva, de una empresa (`empresa_id` NOT NULL):

- `dispositivo_push`: el token de Firebase Cloud Messaging de un teléfono, dueño de UN usuario. UNIQUE (empresa_id,
  token): un token pertenece a un solo usuario y si otro inicia sesión en el mismo teléfono el registro se reasigna.
  `activo` marca los que reciben push. Queda fuera de las copias de seguridad (identificador de dispositivo).

Revisada a mano: solo `create_table` y sus indices. No toca otras tablas ni permisos (las rutas solo exigen sesion).
No importa nada de `app.*`.

Revision ID: f4b8d2a6c139
Revises: e7a3c91d5b28
Create Date: 2026-11-06 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f4b8d2a6c139'
down_revision: Union[str, None] = 'e7a3c91d5b28'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'dispositivo_push',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('empresa_id', sa.Integer(), nullable=False),
        sa.Column('usuario_id', sa.Integer(), nullable=False),
        sa.Column('token', sa.String(length=512), nullable=False),
        sa.Column('plataforma', sa.String(length=15), nullable=False),
        sa.Column('activo', sa.Boolean(), nullable=False),
        sa.Column('creado_en', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('actualizado_en', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("plataforma IN ('android')", name='ck_dispositivo_push_plataforma'),
        sa.ForeignKeyConstraint(['empresa_id'], ['empresa.id']),
        sa.ForeignKeyConstraint(['usuario_id'], ['usuario.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('empresa_id', 'token', name='uq_dispositivo_push_empresa_token'),
    )
    op.create_index('ix_dispositivo_push_empresa_id', 'dispositivo_push', ['empresa_id'], unique=False)
    op.create_index('ix_dispositivo_push_usuario', 'dispositivo_push', ['usuario_id', 'activo'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_dispositivo_push_usuario', table_name='dispositivo_push')
    op.drop_index('ix_dispositivo_push_empresa_id', table_name='dispositivo_push')
    op.drop_table('dispositivo_push')
