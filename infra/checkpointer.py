"""Checkpointer de LangGraph sobre Postgres: lo que permite reanudar un grafo pausado
por `interrupt_on` (aprobacion de nivel 2) despues de un reinicio del proceso.

Alcance de la Fase 1: la dependencia (`langgraph-checkpoint-postgres==3.1.2`) y el
checkpointer en si, verificados contra el Postgres real del compose (ver
tests/test_infra_checkpointer.py). Cablearlo en `create_deep_agent(checkpointer=...)`
y resolver `Command(resume=...)` desde un `thread_id` es trabajo de la Fase 2: necesita
el endpoint `POST /incidentes/{id}/aprobar` (el canal humano real) para tener sentido,
no solo la libreria instalada. Ver docs/plan-aiops.md.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

from langgraph.checkpoint.postgres import PostgresSaver


@contextmanager
def crear_checkpointer(database_url: str | None = None) -> Iterator[PostgresSaver]:
    """Conexion al checkpointer. No crea las tablas (ver `asegurar_tablas`): igual que
    infra/incidentes_postgres.py, eso es responsabilidad de una migracion/setup
    explicito, no de cada conexion."""
    url = database_url or os.environ["DATABASE_URL"]
    with PostgresSaver.from_conn_string(url) as checkpointer:
        yield checkpointer


def asegurar_tablas(database_url: str | None = None) -> None:
    """Crea las tablas del checkpointer (`checkpoints`, `checkpoint_writes`,
    `checkpoint_blobs`, `checkpoint_migrations`) si no existen. Idempotente: seguro de
    llamar en cada arranque. No se modela con Alembic porque la libreria arma su propio
    esquema versionado (`checkpoint_migrations`) y lo gestiona ella misma."""
    with crear_checkpointer(database_url) as checkpointer:
        checkpointer.setup()
