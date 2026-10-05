"""agents/aiops/worker_jobs.py: solo la rama `es_firing=False` (notificar_resuelta_en_origen)
no necesita LLM, asi que es la unica que se prueba en vivo aca. La rama `es_firing=True`
llama a build_agent().invoke(...): requiere ANTHROPIC_API_KEY, no disponible en esta
sesion (ver docstring del modulo)."""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator

import pytest

from agents.aiops import runtime
from agents.aiops.worker_jobs import procesar_alerta_webhook
from domain.aiops_core.modelos import Alerta, Severidad


@pytest.fixture(autouse=True)
def _reset() -> Iterator[None]:
    runtime.reset()
    yield
    runtime.reset()


def test_resolved_audita_sin_abrir_incidente() -> None:
    alerta = Alerta("W1", "ServiceDown", "checkout", "staging", Severidad.MEDIA, "caido")
    resultado = procesar_alerta_webhook(dataclasses.asdict(alerta), False)
    assert "auditada" in resultado
    assert runtime.get_ciclo().incidentes() == []  # nunca se abrio nada
