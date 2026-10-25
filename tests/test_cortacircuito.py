"""El cortacircuito sobrevive al armado del ciclo con Postgres (antes de usar
dataclasses.replace, copiar la politica campo a campo perdia los campos nuevos)."""

from __future__ import annotations

import pytest

from agents.aiops import runtime


def test_armar_postgres_conserva_el_cortacircuito(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIOPS_BREAKER_MAX", "5")
    monkeypatch.setenv("AIOPS_BREAKER_WINDOW_S", "120")
    ciclo = runtime.armar(persistencia="postgres")
    politica = ciclo.politica
    assert (politica.max_acciones_servicio, politica.ventana_cortacircuito_s) == (5, 120.0)
