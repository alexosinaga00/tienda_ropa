"""caja_turno: el turno del cajón de una sucursal, y el permiso caja.supervisar

Tabla `caja_turno` (E21, D24): el turno de caja de una SUCURSAL. Se abre con un monto inicial, se vende y cobra durante el
turno y se cierra contando el efectivo. A lo sumo un turno `abierta` por sucursal (índice único parcial
`ux_caja_turno_abierta`, en PostgreSQL y en SQLite). Estados `abierta`, `cerrada` y `cerrada_auto` (el sistema lo cierra solo
al terminar el día en hora de Bolivia, SIN conteo). Guarda la "foto" al cerrar para que un cierre pasado no cambie.
Además el permiso `caja.supervisar` (ver los cierres, cerrar el turno de otra persona y completar un conteo) para el
administrador y el encargado de sucursal (la producción no corre seeds).

Revisada a mano: solo `create_table` + 2 índices y el permiso. No toca otras tablas. No importa nada de `app.*`.

Revision ID: d3b8f5a1c946
Revises: c7a2e9f4d610
Create Date: 2026-11-08 20:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd3b8f5a1c946'
down_revision: Union[str, None] = 'c7a2e9f4d610'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


CONDICION_ABIERTA = "estado = 'abierta'"
PERMISOS = [
    ('caja.supervisar', 'caja', 'Ver los cierres de caja, cerrar el turno de otra persona y completar un conteo'),
]
ASIGNACIONES = [
    ('administrador', 'caja.supervisar'),
    ('encargado_sucursal', 'caja.supervisar'),
]


def upgrade() -> None:
    op.create_table(
        'caja_turno',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('empresa_id', sa.Integer(), nullable=False),
        sa.Column('sucursal_id', sa.Integer(), nullable=False),
        sa.Column('abierto_por_id', sa.Integer(), nullable=False),
        sa.Column('estado', sa.String(length=15), nullable=False),
        sa.Column('apertura_en', sa.DateTime(), nullable=False),
        sa.Column('monto_inicial', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('observacion_apertura', sa.String(length=300), nullable=True),
        sa.Column('cierre_en', sa.DateTime(), nullable=True),
        sa.Column('cerrado_por_id', sa.Integer(), nullable=True),
        sa.Column('efectivo_contado', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('ventas_efectivo', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('reembolsos_efectivo', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('monto_esperado', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('diferencia', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('cantidad_ventas', sa.Integer(), nullable=True),
        sa.Column('ventas_otros_metodos', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('pendientes_declarados', sa.Integer(), nullable=False),
        sa.Column('observacion_cierre', sa.String(length=300), nullable=True),
        sa.Column('conteo_en', sa.DateTime(), nullable=True),
        sa.Column('conteo_por_id', sa.Integer(), nullable=True),
        sa.Column('observacion_conteo', sa.String(length=300), nullable=True),
        sa.CheckConstraint("estado IN ('abierta','cerrada','cerrada_auto')", name='ck_caja_turno_estado'),
        sa.CheckConstraint('monto_inicial >= 0', name='ck_caja_turno_monto_inicial'),
        sa.CheckConstraint('efectivo_contado IS NULL OR efectivo_contado >= 0', name='ck_caja_turno_contado'),
        sa.CheckConstraint('pendientes_declarados >= 0', name='ck_caja_turno_pendientes'),
        sa.CheckConstraint(
            "(estado = 'abierta' AND cierre_en IS NULL AND efectivo_contado IS NULL) "
            "OR (estado <> 'abierta' AND cierre_en IS NOT NULL AND monto_esperado IS NOT NULL)",
            name='ck_caja_turno_coherencia',
        ),
        sa.CheckConstraint(
            "estado <> 'cerrada' OR (efectivo_contado IS NOT NULL AND diferencia IS NOT NULL)",
            name='ck_caja_turno_cerrada_con_conteo',
        ),
        sa.ForeignKeyConstraint(['empresa_id'], ['empresa.id']),
        sa.ForeignKeyConstraint(['sucursal_id'], ['sucursal.id']),
        sa.ForeignKeyConstraint(['abierto_por_id'], ['usuario.id']),
        sa.ForeignKeyConstraint(['cerrado_por_id'], ['usuario.id']),
        sa.ForeignKeyConstraint(['conteo_por_id'], ['usuario.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_caja_turno_empresa_id', 'caja_turno', ['empresa_id'], unique=False)
    op.create_index('ix_caja_turno_sucursal', 'caja_turno', ['empresa_id', 'sucursal_id', 'apertura_en'], unique=False)
    op.create_index(
        'ux_caja_turno_abierta',
        'caja_turno',
        ['empresa_id', 'sucursal_id'],
        unique=True,
        postgresql_where=sa.text(CONDICION_ABIERTA),
        sqlite_where=sa.text(CONDICION_ABIERTA),
    )

    for codigo, modulo, descripcion in PERMISOS:
        op.execute(
            sa.text(
                "INSERT INTO permiso (codigo, modulo, descripcion) "
                "VALUES (:codigo, :modulo, :descripcion) "
                "ON CONFLICT (codigo) DO NOTHING"
            ).bindparams(codigo=codigo, modulo=modulo, descripcion=descripcion)
        )
    # Si el rol o el permiso no existen (base sin seeds) el SELECT no devuelve filas y no se inserta nada, sin error.
    for rol, permiso in ASIGNACIONES:
        op.execute(
            sa.text(
                "INSERT INTO rol_permiso (rol_id, permiso_id) "
                "SELECT r.id, p.id FROM rol r, permiso p "
                "WHERE r.nombre = :rol AND p.codigo = :permiso "
                "ON CONFLICT DO NOTHING"
            ).bindparams(rol=rol, permiso=permiso)
        )


def downgrade() -> None:
    for codigo, _modulo, _descripcion in PERMISOS:
        op.execute(
            sa.text(
                "DELETE FROM rol_permiso WHERE permiso_id IN (SELECT id FROM permiso WHERE codigo = :codigo)"
            ).bindparams(codigo=codigo)
        )
        op.execute(sa.text("DELETE FROM permiso WHERE codigo = :codigo").bindparams(codigo=codigo))
    op.drop_index(
        'ux_caja_turno_abierta',
        table_name='caja_turno',
        postgresql_where=sa.text(CONDICION_ABIERTA),
        sqlite_where=sa.text(CONDICION_ABIERTA),
    )
    op.drop_index('ix_caja_turno_sucursal', table_name='caja_turno')
    op.drop_index('ix_caja_turno_empresa_id', table_name='caja_turno')
    op.drop_table('caja_turno')
