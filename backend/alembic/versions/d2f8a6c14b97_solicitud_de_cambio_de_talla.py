"""solicitud de cambio de talla o color por el cliente (Etapa 2 del CU-17)

La solicitud NO es una tabla nueva: es una `devolucion` en estado 'pendiente' (el estado ya existia, pero hoy toda
devolucion nace 'aprobada'). Para que el cliente pida una talla o un color y el cajero la resuelva despues hacen
falta:

- `devolucion_detalle.variante_nueva_id` (nullable, FK a `producto_variante`): la variante que se entrega en lugar de
  la devuelta. NULL = devolucion simple (todas las filas existentes quedan asi).
- `devolucion.resuelta_por_id` (nullable, FK a `usuario`), `devolucion.resuelta_en` y `devolucion.motivo_rechazo`
  (texto de hasta 300): quien aprobo, rechazo o cancelo, cuando y, si se rechazo, por que.
- El CHECK `ck_devolucion_estado` admite dos estados mas: 'cancelada' (la cancela el cliente) y 'vencida' (nadie la
  atendio a tiempo).

Revisada a mano: solo columnas nullable y el reemplazo de un CHECK, sin tocar datos existentes ni otras tablas.
No importa nada de `app.*`.

Revision ID: d2f8a6c14b97
Revises: c5e1b7a38d92
Create Date: 2026-11-04 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd2f8a6c14b97'
down_revision: Union[str, None] = 'c5e1b7a38d92'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'devolucion_detalle',
        sa.Column('variante_nueva_id', sa.Integer(), sa.ForeignKey('producto_variante.id'), nullable=True),
    )
    op.add_column('devolucion', sa.Column('resuelta_por_id', sa.Integer(), sa.ForeignKey('usuario.id'), nullable=True))
    op.add_column('devolucion', sa.Column('resuelta_en', sa.DateTime(), nullable=True))
    op.add_column('devolucion', sa.Column('motivo_rechazo', sa.String(length=300), nullable=True))

    op.drop_constraint('ck_devolucion_estado', 'devolucion', type_='check')
    op.create_check_constraint(
        'ck_devolucion_estado',
        'devolucion',
        "estado IN ('pendiente','aprobada','rechazada','cancelada','vencida')",
    )


def downgrade() -> None:
    # Las solicitudes cancelada o vencida no caben en el CHECK anterior: se vuelven 'rechazada' (el estado final
    # equivalente) antes de restaurarlo. No se pierde ninguna fila.
    op.execute(sa.text("UPDATE devolucion SET estado = 'rechazada' WHERE estado IN ('cancelada', 'vencida')"))
    op.drop_constraint('ck_devolucion_estado', 'devolucion', type_='check')
    op.create_check_constraint('ck_devolucion_estado', 'devolucion', "estado IN ('pendiente','aprobada','rechazada')")

    op.drop_column('devolucion', 'motivo_rechazo')
    op.drop_column('devolucion', 'resuelta_en')
    op.drop_column('devolucion', 'resuelta_por_id')
    op.drop_column('devolucion_detalle', 'variante_nueva_id')
