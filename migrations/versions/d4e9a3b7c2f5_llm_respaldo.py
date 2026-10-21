"""respaldo de LLM: proveedor y modelo alternativos si el principal falla

Revision ID: d4e9a3b7c2f5
Revises: c3d8f2a6b1e4
Create Date: 2026-10-21

Si la corrida con el modelo principal falla (proveedor caido, sin saldo, timeout), el
worker retoma el mismo incidente con este modelo (agents/aiops/worker_jobs.py). Opcional:
sin respaldo el comportamiento es el de siempre.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d4e9a3b7c2f5"
down_revision: str | Sequence[str] | None = "c3d8f2a6b1e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("aiops_llm_activo", sa.Column("respaldo_proveedor", sa.Text(), nullable=True))
    op.add_column("aiops_llm_activo", sa.Column("respaldo_modelo", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("aiops_llm_activo", "respaldo_modelo")
    op.drop_column("aiops_llm_activo", "respaldo_proveedor")
