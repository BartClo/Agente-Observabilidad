"""Integracion contra el Postgres real del compose: confirma que el checkpointer de
LangGraph (langgraph-checkpoint-postgres, ver docs/open-questions.md) arma sus tablas y
hace un put/get redondo real, sin un grafo de deepagents de por medio (eso es Fase 2)."""

from __future__ import annotations

import os
from collections.abc import Iterator

import psycopg
import pytest
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import Checkpoint, empty_checkpoint

from infra.checkpointer import asegurar_tablas, crear_checkpointer


@pytest.fixture(autouse=True)
def _tablas() -> Iterator[None]:
    asegurar_tablas()
    yield
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        conn.execute("DELETE FROM checkpoints")


def test_setup_crea_las_tablas_del_checkpointer() -> None:
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        filas = conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_name LIKE 'checkpoint%' ORDER BY table_name"
        ).fetchall()
    assert {f[0] for f in filas} >= {"checkpoints", "checkpoint_writes", "checkpoint_blobs"}


def test_put_y_get_redondo() -> None:
    config: RunnableConfig = {"configurable": {"thread_id": "INC-TEST-1", "checkpoint_ns": ""}}
    checkpoint: Checkpoint = empty_checkpoint()
    with crear_checkpointer() as cp:
        cp.put(config, checkpoint, {"source": "update", "step": 1}, {})
        tupla = cp.get_tuple(config)
    assert tupla is not None
    assert tupla.checkpoint["id"] == checkpoint["id"]
