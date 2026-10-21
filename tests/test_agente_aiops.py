"""El agente que corre el worker (agents/aiops/agente.py): un agente unico con las tools
del ciclo L1 y nada mas."""

from __future__ import annotations

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
