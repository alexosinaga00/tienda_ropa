"""metodo pago qr_online

El método 'qr_online' solo lo creaba scripts/seed_pagos.py, que no corre en
el despliegue (start.sh solo aplica migraciones). Una base sin ese seed
respondía 404 "Método de pago 'qr_online' no encontrado" al pagar con QR.
Es idempotente: crea la fila si falta y la deja activa si estaba dada de baja.

Revision ID: 78a0130804a0
Revises: 6f4501e2abc6
Create Date: 2026-09-20 12:10:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '78a0130804a0'
down_revision: Union[str, None] = '6f4501e2abc6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO metodo_pago (codigo, nombre, requiere_pasarela, disponible_caja, disponible_online, activo)
        VALUES ('qr_online', 'Pago con QR (online)', true, false, true, true)
        ON CONFLICT (codigo) DO UPDATE
        SET requiere_pasarela = true, disponible_online = true, activo = true
        """
    )


def downgrade() -> None:
    # Baja lógica, no DELETE físico: puede haber pagos que ya lo referencian.
    op.execute("UPDATE metodo_pago SET activo = false WHERE codigo = 'qr_online'")
