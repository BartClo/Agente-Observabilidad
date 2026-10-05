"""agents/aiops/worker_jobs.py arma su propio Ciclo contra Postgres (persistencia
explicita, ver runtime.armar): esto ya es integracion, no una unidad pura, igual que
tests/test_infra_incidentes_postgres.py. Solo la rama `es_firing=False`
(notificar_resuelta_en_origen) se prueba en vivo aca: la rama `es_firing=True` llama
a build_agent().invoke(...), que requiere ANTHROPIC_API_KEY (no disponible en esta
sesion, ver docstring del modulo)."""

from __future__ import annotations

import dataclasses
import os
from collections.abc import Iterator

import psycopg
import pytest

from agents.aiops.worker_jobs import procesar_alerta_webhook
from domain.aiops_core.modelos import Alerta, Severidad
from infra.incidentes_postgres import RepositorioIncidentesPostgres


@pytest.fixture(autouse=True)
def _limpiar() -> Iterator[None]:
    yield
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        conn.execute("DELETE FROM aiops_incidentes WHERE id = 'INC-W1'")


def test_resolved_audita_sin_abrir_incidente() -> None:
    alerta = Alerta("W1", "ServiceDown", "checkout", "staging", Severidad.MEDIA, "caido")
    resultado = procesar_alerta_webhook(dataclasses.asdict(alerta), False)
    assert "auditada" in resultado
    assert RepositorioIncidentesPostgres().obtener("INC-W1") is None  # nunca se abrio nada
