"""jira: configuracion de la conexion y tickets vistos (bandeja de escritura)

Revision ID: f6a1c9d2e4b7
Revises: e5f0b4c8d3a6
Create Date: 2026-11-03

aiops_jira_config es una fila unica (id = true), como aiops_llm_activo. aiops_jira_tickets
garantiza que cada ticket se procesa una sola vez y guarda el comentario pendiente de
publicar (ver agents/aiops/jira_poller.py).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "f6a1c9d2e4b7"
down_revision: str | Sequence[str] | None = "e5f0b4c8d3a6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "aiops_jira_config",
        sa.Column("id", sa.Boolean(), primary_key=True, server_default=sa.true()),
        sa.Column("sitio", sa.Text()),
        sa.Column("correo", sa.Text()),
        sa.Column("token_cifrado", sa.Text()),
        sa.Column("sufijo", sa.Text()),
        sa.Column("tablero_id", sa.Integer()),
        sa.Column("tablero_nombre", sa.Text()),
        sa.Column("entrada", JSONB()),
        sa.Column("resuelto", JSONB()),
        sa.Column("escalado", JSONB()),
        sa.Column("intervalo_s", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("activo", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("actualizado_por", sa.Text()),
        sa.Column("actualizado_en", sa.DateTime(timezone=True)),
        sa.Column("ultimo_sondeo_en", sa.DateTime(timezone=True)),
        sa.Column("ultimo_sondeo_tickets", sa.Integer()),
        sa.Column("ultimo_error", sa.Text()),
        sa.CheckConstraint("id", name="aiops_jira_config_fila_unica"),
    )
    op.execute("INSERT INTO aiops_jira_config (id) VALUES (true)")
    op.create_table(
        "aiops_jira_tickets",
        sa.Column("clave", sa.Text(), primary_key=True),
        sa.Column("incidente_id", sa.Text(), nullable=False),
        sa.Column(
            "visto_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("estado", sa.Text(), nullable=False, server_default="encolado"),
        sa.Column("destino", sa.Text()),
        sa.Column("texto", sa.Text()),
        sa.Column("intentos", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ultimo_error", sa.Text()),
    )
    op.create_index("ix_aiops_jira_tickets_incidente", "aiops_jira_tickets", ["incidente_id"])
    op.create_index("ix_aiops_jira_tickets_estado", "aiops_jira_tickets", ["estado"])


def downgrade() -> None:
    op.drop_table("aiops_jira_tickets")
    op.drop_table("aiops_jira_config")
