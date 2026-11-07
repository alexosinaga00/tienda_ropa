"""Pedido sin conexión: el estado `incierto` (PayPal pudo haber cobrado y no se supo)

Antes, un cobro con resultado desconocido (la respuesta de PayPal se perdió, la captura quedó pendiente) deshacía todo y no
dejaba rastro; si antes del reintento el stock se agotaba, el pedido se rechazaba con "no se cobró" aunque PayPal SÍ había
cobrado. Ahora ese caso deja una fila `incierto` con el monto, y el reintento le pregunta a PayPal antes de decidir.

Solo cambia el CHECK `ck_pedido_diferido_estado` (suma 'incierto'): sin columnas ni datos nuevos. La baja de versión convierte
las filas `incierto` en `rechazado` (motivo `cobro_incierto`) para poder restaurar el CHECK anterior. Revisada a mano.
No importa nada de `app.*`.

Revision ID: b8d4f1a7c935
Revises: a3c7e9d1b542
Create Date: 2026-11-07 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b8d4f1a7c935'
down_revision: Union[str, None] = 'a3c7e9d1b542'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint('ck_pedido_diferido_estado', 'pedido_diferido', type_='check')
    op.create_check_constraint(
        'ck_pedido_diferido_estado', 'pedido_diferido', "estado IN ('en_proceso','incierto','cobrado','rechazado')"
    )


def downgrade() -> None:
    op.execute(
        sa.text("UPDATE pedido_diferido SET estado = 'rechazado', motivo = COALESCE(motivo, 'cobro_incierto') WHERE estado = 'incierto'")
    )
    op.drop_constraint('ck_pedido_diferido_estado', 'pedido_diferido', type_='check')
    op.create_check_constraint(
        'ck_pedido_diferido_estado', 'pedido_diferido', "estado IN ('en_proceso','cobrado','rechazado')"
    )
