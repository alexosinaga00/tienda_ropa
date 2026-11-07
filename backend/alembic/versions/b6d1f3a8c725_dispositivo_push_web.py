"""Push web: el navegador tambien es una plataforma de `dispositivo_push`

El token de Firebase Cloud Messaging de un navegador (push web) se guarda en la misma tabla que el de un telefono. Lo unico
que cambia es el CHECK `ck_dispositivo_push_plataforma`, que pasa de ('android') a ('android','web').

Revisada a mano: solo el reemplazo de un CHECK, sin columnas ni datos nuevos. El tope de dispositivos activos por usuario
(`push_max_dispositivos_por_usuario`) sigue siendo uno solo, compartido entre android y web.
La baja de version borra las filas 'web' (son tokens de navegador que se vuelven a registrar al iniciar sesion; no son
datos de negocio) para que el CHECK anterior se pueda restaurar.
No importa nada de `app.*`.

Revision ID: b6d1f3a8c725
Revises: f4b8d2a6c139
Create Date: 2026-11-07 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b6d1f3a8c725'
down_revision: Union[str, None] = 'f4b8d2a6c139'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint('ck_dispositivo_push_plataforma', 'dispositivo_push', type_='check')
    op.create_check_constraint(
        'ck_dispositivo_push_plataforma', 'dispositivo_push', "plataforma IN ('android','web')"
    )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM dispositivo_push WHERE plataforma = 'web'"))
    op.drop_constraint('ck_dispositivo_push_plataforma', 'dispositivo_push', type_='check')
    op.create_check_constraint('ck_dispositivo_push_plataforma', 'dispositivo_push', "plataforma IN ('android')")
