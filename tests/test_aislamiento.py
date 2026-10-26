"""Aislamiento entre corridas del experimento: cada corrida inyecta una falla en el mismo
servicio, asi que sin aislamiento una corrida contamina a la siguiente (logs FATAL de la
anterior; el cortacircuito cuenta las inyecciones como recurrencia)."""

from __future__ import annotations

import pytest

from agents.aiops import runtime
from scripts import experimento


def test_el_runtime_lee_la_ventana_de_logs_del_entorno(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIOPS_LOGS_VENTANA_S", "60")
    assert runtime.armar(persistencia="postgres")._logs_ventana == 60.0  # noqa: SLF001
    monkeypatch.delenv("AIOPS_LOGS_VENTANA_S")
    assert runtime.armar(persistencia="postgres")._logs_ventana == 0.0  # noqa: SLF001


def test_el_experimento_aisla_cada_corrida_de_la_anterior() -> None:
    flags = experimento._env_ciclo(3, "6443")  # noqa: SLF001
    assert "AIOPS_BREAKER_MAX=0" in flags  # las inyecciones repetidas no son recurrencia real
    assert "AIOPS_LOGS_VENTANA_S=60" in flags  # el agente ve los logs de ESTA falla


def test_el_experimento_fija_la_configuracion_del_rag() -> None:
    flags = experimento._env_ciclo(3, "6443")  # noqa: SLF001
    assert "AIOPS_RAG_ORIGENES=repo" in flags  # los PDF subidos no entran en lo medido
    assert "AIOPS_RAG=1" in flags and "AIOPS_RAG_K=4" in flags
    assert any(f.startswith("AIOPS_RAG_MIN_SIM=") for f in flags)


def test_sin_rag_apaga_el_brazo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(experimento, "RAG", "0")
    assert "AIOPS_RAG=0" in experimento._env_ciclo(3, "6443")  # noqa: SLF001


def test_el_piso_del_experimento_es_el_calibrado() -> None:
    from agents.aiops import conocimiento

    assert experimento.CONFIG_RAG["AIOPS_RAG_MIN_SIM"] == conocimiento.MIN_SIM_DEFECTO
