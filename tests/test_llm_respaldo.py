"""Respaldo de LLM a nivel de corrida (agents/aiops/worker_jobs.py): si el modelo
principal falla a mitad de un incidente, el respaldo lo retoma desde donde quedo.

El agente es falso: lo que se prueba es la logica de respaldo, el registro del modelo
usado y la auditoria, no a ningun proveedor."""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest

from agents.aiops import runtime
from agents.aiops.worker_jobs import ContadorTurnos, atender_con_agente
from domain.aiops_core.modelos import Alerta, Estado, Severidad


class AgenteFalso:
    def __init__(
        self,
        *,
        falla: Exception | None = None,
        escala: Any = None,
        turnos: int = 0,
        tools: int = 0,
    ) -> None:
        self.falla = falla
        self.escala = escala
        self.turnos = turnos
        self.tools = tools
        self.pedidos: list[str] = []

    def invoke(self, entrada: dict[str, Any], config: dict[str, Any]) -> None:
        self.pedidos.append(entrada["messages"][0]["content"])
        (contador,) = [h for h in config["callbacks"] if isinstance(h, ContadorTurnos)]
        for _ in range(self.turnos):
            contador.on_chat_model_start({}, [])
        for _ in range(self.tools):
            contador.on_tool_start({}, "")
        if self.escala is not None:
            self.escala()
        if self.falla is not None:
            raise self.falla


@pytest.fixture
def incidente(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[Any, str, Alerta]]:
    ciclo = runtime.armar(persistencia="postgres")
    alerta = Alerta("resp-1", "ServiceDown", "checkout", "dev", Severidad.ALTA, "r")
    inc = ciclo.abrir_desde_alerta(alerta)
    runtime.reset(ciclo)
    yield ciclo, inc.id, alerta
    runtime.reset()
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        conn.execute("DELETE FROM aiops_incidentes")
        conn.execute("DELETE FROM aiops_eventos_auditoria")


def _usar(
    monkeypatch: pytest.MonkeyPatch,
    principal: AgenteFalso,
    respaldo: AgenteFalso | None,
) -> None:
    agentes = {"M1": principal, "M2": respaldo}
    monkeypatch.setattr("app.main.modelo_de_la_ui", lambda: ("M1", "deepseek:deepseek-chat"))
    monkeypatch.setattr(
        "app.main.respaldo_de_la_ui", lambda: ("M2", "google:gemini-x") if respaldo else None
    )
    monkeypatch.setattr("agents.aiops.agente.construir", lambda modelo=None: agentes[modelo])


def test_si_el_principal_falla_el_respaldo_retoma(
    incidente: tuple[Any, str, Alerta], monkeypatch: pytest.MonkeyPatch
) -> None:
    ciclo, inc_id, alerta = incidente
    principal = AgenteFalso(falla=ConnectionError("proveedor caido"), turnos=2, tools=1)
    respaldo = AgenteFalso(
        escala=lambda: ciclo.escalar(inc_id, "lo resolvio el respaldo"), turnos=1, tools=3
    )
    _usar(monkeypatch, principal, respaldo)

    atender_con_agente(ciclo, inc_id, alerta)  # no lanza: el respaldo termino el trabajo

    assert len(principal.pedidos) == 1 and len(respaldo.pedidos) == 1
    assert "estado_incidente" in respaldo.pedidos[0]  # sabe que retoma, no que empieza
    assert "estado_incidente" not in principal.pedidos[0]
    inc = ciclo.incidente(inc_id)
    assert inc.estado is Estado.ESCALADO
    assert inc.modelo_llm == "deepseek:deepseek-chat -> google:gemini-x"
    # el esfuerzo de las dos corridas se suma al mismo incidente
    assert (inc.turnos_llm, inc.llamadas_tools) == (3, 4)
    (evento,) = [e for e in ciclo.auditoria.eventos if e.tipo == "llm_respaldo"]
    assert evento.datos == {
        "desde": "deepseek:deepseek-chat",
        "hacia": "google:gemini-x",
        "error": "ConnectionError",
    }


def test_sin_respaldo_el_error_se_propaga_como_siempre(
    incidente: tuple[Any, str, Alerta], monkeypatch: pytest.MonkeyPatch
) -> None:
    ciclo, inc_id, alerta = incidente
    _usar(monkeypatch, AgenteFalso(falla=ConnectionError("caido")), None)
    with pytest.raises(ConnectionError):
        atender_con_agente(ciclo, inc_id, alerta)
    assert ciclo.incidente(inc_id).modelo_llm == "deepseek:deepseek-chat"


def test_si_fallan_los_dos_se_propaga_el_primer_error_y_quedan_ambos_registrados(
    incidente: tuple[Any, str, Alerta], monkeypatch: pytest.MonkeyPatch
) -> None:
    ciclo, inc_id, alerta = incidente
    _usar(
        monkeypatch,
        AgenteFalso(falla=ConnectionError("primero")),
        AgenteFalso(falla=TimeoutError("segundo")),
    )
    with pytest.raises(ConnectionError, match="primero"):
        atender_con_agente(ciclo, inc_id, alerta)
    assert ciclo.incidente(inc_id).modelo_llm == "deepseek:deepseek-chat -> google:gemini-x"


def test_si_el_incidente_ya_termino_no_se_llama_al_respaldo(
    incidente: tuple[Any, str, Alerta], monkeypatch: pytest.MonkeyPatch
) -> None:
    ciclo, inc_id, alerta = incidente
    principal = AgenteFalso(
        falla=ConnectionError("cayo despues de escalar"),
        escala=lambda: ciclo.escalar(inc_id, "ya escalado"),
    )
    respaldo = AgenteFalso()
    _usar(monkeypatch, principal, respaldo)
    with pytest.raises(ConnectionError):
        atender_con_agente(ciclo, inc_id, alerta)
    assert respaldo.pedidos == []  # nada que retomar
