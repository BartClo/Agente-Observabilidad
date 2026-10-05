"""Integracion contra el Postgres real del compose (requiere `make migrate`)."""

from __future__ import annotations

import os
from collections.abc import Iterator

import psycopg
import pytest

from domain.aiops_core.auditoria import Auditoria
from infra.auditoria_postgres import crear_sink_postgres, eventos_de_incidente


@pytest.fixture(autouse=True)
def _limpiar() -> Iterator[None]:
    yield
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        conn.execute("DELETE FROM aiops_eventos_auditoria")


def test_sink_postgres_persiste_y_se_puede_releer() -> None:
    aud = Auditoria(on_evento=crear_sink_postgres())
    aud.registrar("INC-1", "abierto", alerta="ServiceDown")
    aud.registrar("INC-1", "confirmacion", confirmada=True)
    aud.registrar("INC-2", "abierto", alerta="DiskUsageHigh")

    eventos = eventos_de_incidente("INC-1")
    assert [e.tipo for e in eventos] == ["abierto", "confirmacion"]
    assert eventos[0].datos == {"alerta": "ServiceDown"}
    assert eventos_de_incidente("INC-no-existe") == []
