"""tablas aiops: incidentes, eventos_auditoria, kill_switch

Revision ID: 9906268772d6
Revises:
Create Date: 2026-10-05 15:42:42.556544

Sin ORM: las columnas indexadas (id, estado, servicio) sirven para listar/filtrar sin
deserializar; `datos`/`incidente` JSONB guardan el dataclass completo tal como lo arma
infra/incidentes_postgres.py. Ver docs/plan-aiops.md Fase 1: se eligio JSONB en vez de
normalizar acciones/alerta en tablas aparte para no duplicar el shape de los dataclasses
de domain/aiops_core/modelos.py en un esquema relacional separado (menos superficie que
mantener sincronizada; Postgres igual permite indexar y consultar JSONB si hiciera falta).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9906268772d6"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "aiops_incidentes",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("estado", sa.Text(), nullable=False),
        sa.Column("servicio", sa.Text(), nullable=False),
        sa.Column("incidente", sa.JSON(), nullable=False),
        sa.Column(
            "actualizado_en",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("aiops_incidentes_estado_idx", "aiops_incidentes", ["estado"])
    op.create_index("aiops_incidentes_servicio_idx", "aiops_incidentes", ["servicio"])

    op.create_table(
        "aiops_eventos_auditoria",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("incidente_id", sa.Text(), nullable=False),
        sa.Column("tipo", sa.Text(), nullable=False),
        sa.Column("datos", sa.JSON(), nullable=False),
    )
    op.create_index(
        "aiops_eventos_auditoria_incidente_idx", "aiops_eventos_auditoria", ["incidente_id"]
    )

    op.create_table(
        "aiops_kill_switch",
        sa.Column("id", sa.Boolean(), primary_key=True, server_default=sa.true()),
        sa.Column("activo", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("usuario", sa.Text(), nullable=True),
        sa.Column("motivo", sa.Text(), nullable=True),
        sa.Column(
            "actualizado_en",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        # fila unica: `id` siempre True (equivalente a un CHECK(id) + PK de 1 valor).
        sa.CheckConstraint("id = true", name="aiops_kill_switch_fila_unica"),
    )
    op.execute("INSERT INTO aiops_kill_switch (id, activo) VALUES (true, false)")


def downgrade() -> None:
    op.drop_table("aiops_kill_switch")
    op.drop_table("aiops_eventos_auditoria")
    op.drop_table("aiops_incidentes")
