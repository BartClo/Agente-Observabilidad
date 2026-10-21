"""bandeja de salida de notificaciones (Google Chat)

Revision ID: c3d8f2a6b1e4
Revises: b7c2e1f4a9d0
Create Date: 2026-10-21

Patron outbox: el aviso se guarda en la misma base que la auditoria y despues se entrega.
Si Google Chat esta caido el aviso no se pierde: queda `pendiente` y se reintenta con
espera creciente (infra/notificaciones.py). `clave` (incidente + tipo + instante del
evento) evita avisos duplicados si el mismo evento se registra dos veces.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3d8f2a6b1e4"
down_revision: str | Sequence[str] | None = "b7c2e1f4a9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "aiops_notificaciones",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "creada_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("clave", sa.Text(), nullable=False, unique=True),
        sa.Column("incidente_id", sa.Text(), nullable=False),
        sa.Column("tipo", sa.Text(), nullable=False),
        sa.Column("texto", sa.Text(), nullable=False),
        sa.Column("estado", sa.Text(), nullable=False, server_default="pendiente"),
        sa.Column("intentos", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "proximo_intento",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("ultimo_error", sa.Text(), nullable=True),
        sa.Column("enviada_en", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "estado IN ('pendiente', 'enviada', 'fallida')", name="aiops_notificaciones_estado"
        ),
    )
    op.create_index(
        "aiops_notificaciones_pendientes", "aiops_notificaciones", ["estado", "proximo_intento"]
    )


def downgrade() -> None:
    op.drop_table("aiops_notificaciones")
