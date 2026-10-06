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
from typing import Any

import psycopg
import pytest

from agents.aiops.worker_jobs import procesar_alerta_webhook
from domain.aiops_core.modelos import Alerta, Severidad
from infra.incidentes_postgres import RepositorioIncidentesPostgres


@pytest.fixture(autouse=True)
def _limpiar() -> Iterator[None]:
    yield
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        conn.execute("DELETE FROM aiops_incidentes WHERE id IN ('INC-W1', 'INC-W2')")


def test_resolved_audita_sin_abrir_incidente() -> None:
    alerta = Alerta("W1", "ServiceDown", "checkout", "staging", Severidad.MEDIA, "caido")
    resultado = procesar_alerta_webhook(dataclasses.asdict(alerta), False)
    assert "auditada" in resultado
    assert RepositorioIncidentesPostgres().obtener("INC-W1") is None  # nunca se abrio nada


def _redis_disponible() -> bool:
    try:
        from infra.redis_client import get_redis

        return bool(get_redis().ping())
    except Exception:
        return False


requiere_redis = pytest.mark.skipif(not _redis_disponible(), reason="profile redis no levantado")


@requiere_redis
def test_firing_las_tools_del_agente_ven_el_incidente(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bug de la Fase 3 encontrado en la Fase 6: el worker abria el incidente en un Ciclo
    Postgres, pero las tools del agente usan runtime.get_ciclo() (otro Ciclo, en
    memoria) y respondian 'no existe'. Sin LLM: un agente falso llama a las tools
    REALES, como haria el LLM, y tienen que encontrar el incidente."""
    import re

    from agents.aiops import runtime, tools

    vistos: list[str] = []

    class AgenteFalso:
        def invoke(self, entrada: dict[str, Any], config: Any = None) -> dict[str, Any]:
            pedido = entrada["messages"][0]["content"]
            inc_id = re.search(r"incidente (\S+) \(", pedido).group(1)  # type: ignore[union-attr]
            vistos.append(tools.estado_incidente(inc_id))
            return {"messages": []}

    monkeypatch.setattr("app.main.build_agent", lambda: AgenteFalso())
    alerta = Alerta("W2", "ServiceDown", "checkout", "dev", Severidad.ALTA, "caido")
    try:
        procesar_alerta_webhook(dataclasses.asdict(alerta), True)
    finally:
        runtime.reset()
    assert len(vistos) == 1
    assert not vistos[0].startswith("ERROR"), vistos[0]
    assert "INC-W2" in vistos[0]


@requiere_redis
def test_lock_un_incidente_por_servicio_a_la_vez(monkeypatch: pytest.MonkeyPatch) -> None:
    from agents.aiops.worker_jobs import ServicioOcupado, bloqueo_servicio

    monkeypatch.setenv("AIOPS_LOCK_ESPERA_S", "0.2")
    with bloqueo_servicio("svc-lock-test"):
        with pytest.raises(ServicioOcupado):
            with bloqueo_servicio("svc-lock-test"):
                pass  # pragma: no cover
        with bloqueo_servicio("otro-servicio"):  # otro servicio no se bloquea
            pass
    with bloqueo_servicio("svc-lock-test"):  # liberado al salir
        pass


def test_tokens_de_suma_todos_los_modelos() -> None:
    """Orquestador y subagente pueden usar modelos distintos: se suman todos."""
    from agents.aiops.worker_jobs import tokens_de

    uso = {
        "claude-orquestador": {"input_tokens": 1000, "output_tokens": 50, "total_tokens": 1050},
        "claude-subagente": {"input_tokens": 4000, "output_tokens": 600, "total_tokens": 4600},
    }
    assert tokens_de(uso) == (5000, 650)
    assert tokens_de({}) == (0, 0)


@requiere_redis
def test_firing_registra_tokens_aunque_el_agente_falle(monkeypatch: pytest.MonkeyPatch) -> None:
    """El callback de uso llega via config; si el agente revienta a mitad, los tokens ya
    gastados igual quedan en el incidente."""
    from agents.aiops import runtime

    class AgenteQueGastaYFalla:
        def invoke(self, entrada: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
            (cb,) = config["callbacks"]
            cb.usage_metadata["modelo-x"] = {"input_tokens": 700, "output_tokens": 70}
            raise RuntimeError("el LLM se cayo")

    monkeypatch.setattr("app.main.build_agent", lambda: AgenteQueGastaYFalla())
    alerta = Alerta("W2", "ServiceDown", "checkout", "dev", Severidad.ALTA, "caido")
    try:
        with pytest.raises(RuntimeError, match="se cayo"):
            procesar_alerta_webhook(dataclasses.asdict(alerta), True)
    finally:
        runtime.reset()
    inc = RepositorioIncidentesPostgres().obtener("INC-W2")
    assert inc is not None and (inc.tokens_entrada, inc.tokens_salida) == (700, 70)
