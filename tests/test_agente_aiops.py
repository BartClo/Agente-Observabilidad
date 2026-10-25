"""El agente que corre el worker (agents/aiops/agente.py): un agente unico con las tools
del ciclo L1 y nada mas."""

from __future__ import annotations

import re
from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from agents.aiops import agente, runtime
from domain.aiops_core.ciclo import Ciclo


class ModeloConTools(GenericFakeChatModel):
    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
        self.__dict__.setdefault("vistas", []).append([t.name for t in tools])
        return self


def test_solo_tiene_las_tools_del_ciclo_l1() -> None:
    nombres = {t.__name__ for t in agente._definicion()["tools"]}
    assert nombres == {
        "listar_alertas_activas", "abrir_incidente", "confirmar_anomalia", "consultar_logs",
        "clasificar_incidente", "registrar_diagnostico", "ejecutar_remediacion",
        "ejecutar_remediacion_con_aprobacion", "verificar_recuperacion", "revertir_accion",
        "escalar_a_humano", "cerrar_incidente", "descartar_falso_positivo", "estado_incidente",
    }  # fmt: skip
    # sin buscar_documentos (el runbook llega con clasificar_incidente), ni archivos, ni task
    assert "buscar_documentos" not in nombres


def test_corre_y_ejecuta_una_tool_real() -> None:
    runtime.reset()
    modelo = ModeloConTools(
        messages=iter(
            [
                AIMessage(
                    "", tool_calls=[{"name": "listar_alertas_activas", "args": {}, "id": "1"}]
                ),
                AIMessage("listo"),
            ]
        )
    )
    resultado = agente.construir(modelo).invoke({"messages": [{"role": "user", "content": "hola"}]})
    tipos = [m.type for m in resultado["messages"]]
    assert tipos == ["human", "ai", "tool", "ai"]
    assert resultado["messages"][2].name == "listar_alertas_activas"
    assert modelo.__dict__["vistas"][0] == [t.__name__ for t in agente._definicion()["tools"]]
    runtime.reset()


def test_modelo_por_defecto_es_el_de_agent_yaml() -> None:
    assert agente.modelo_por_defecto() == "anthropic:claude-sonnet-5"


def test_sin_interrupt_on_la_aprobacion_la_sigue_exigiendo_el_dominio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Quitar deepagents (y su interrupt_on) no abre un hueco: aprobarse solo no existe."""
    from agents.aiops import tools

    runtime.reset()
    ciclo: Ciclo = runtime.get_ciclo()
    inc = ciclo.abrir(ciclo.alertas_activas()[0].split(" | ")[0])
    assert tools.ejecutar_remediacion_con_aprobacion(inc.id).startswith("ERROR")
    runtime.reset()


def test_el_pedido_dice_que_el_incidente_ya_esta_abierto() -> None:
    from agents.aiops.worker_jobs import pedido_de
    from domain.aiops_core.modelos import Alerta, Severidad

    alerta = Alerta("a1", "PodFailed", "api", "dev", Severidad.ALTA, "r")
    pedido = pedido_de("INC-1", alerta)
    assert "confirmar_anomalia" in pedido and "INC-1" in pedido
    assert "no uses listar_alertas_activas ni abrir_incidente" in pedido
    # los tests del worker extraen el id con esta expresion: no romperla
    coincidencia = re.search(r"incidente (\S+) \(", pedido)
    assert coincidencia is not None and coincidencia.group(1) == "INC-1"


def test_el_interruptor_elige_el_agente_de_la_plantilla(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.main.build_agent", lambda modelo=None: ("plantilla", modelo))
    monkeypatch.setenv("AIOPS_AGENTE", "deepagents")
    assert agente.construir("M") == ("plantilla", "M")
    monkeypatch.setenv("AIOPS_AGENTE", "unico")
    unico = agente.construir(ModeloConTools(messages=iter([])))
    assert unico.get_graph() is not None  # un grafo de LangChain, no la tupla de la plantilla
