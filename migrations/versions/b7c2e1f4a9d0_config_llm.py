"""configuracion del LLM: credenciales cifradas por proveedor y seleccion activa

Revision ID: b7c2e1f4a9d0
Revises: 9906268772d6
Create Date: 2026-10-06

La API key nunca se guarda en claro: `api_key_cifrada` es Fernet con AIOPS_SECRETS_KEY
(ver infra/llm_config.py). `sufijo` son los ultimos 4 caracteres, para mostrar en la UI
sin descifrar. `aiops_llm_activo` es una fila unica (como aiops_kill_switch): sin
proveedor elegido, el agente usa el modelo de agent.yaml / ORCHESTRATOR_MODEL.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7c2e1f4a9d0"
down_revision: str | Sequence[str] | None = "9906268772d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "aiops_llm_credenciales",
        sa.Column("proveedor", sa.Text(), primary_key=True),
        sa.Column("api_key_cifrada", sa.Text(), nullable=False),
        sa.Column("sufijo", sa.Text(), nullable=False),
        sa.Column("actualizado_por", sa.Text(), nullable=False),
        sa.Column(
            "actualizado_en",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_table(
        "aiops_llm_activo",
        sa.Column("id", sa.Boolean(), primary_key=True, server_default=sa.true()),
        sa.Column("proveedor", sa.Text(), nullable=True),
        sa.Column("modelo", sa.Text(), nullable=True),
        sa.Column("actualizado_por", sa.Text(), nullable=True),
        sa.Column(
            "actualizado_en",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("id = true", name="aiops_llm_activo_fila_unica"),
    )
    op.execute("INSERT INTO aiops_llm_activo (id) VALUES (true)")


def downgrade() -> None:
    op.drop_table("aiops_llm_activo")
    op.drop_table("aiops_llm_credenciales")
