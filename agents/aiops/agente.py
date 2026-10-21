"""El agente aiops tal como lo corre el worker: UN agente de tool-calling con las tools
del ciclo L1 y su prompt (agents/aiops/agent.yaml), sin orquestador ni subagente.

Por que no el orquestador + subagente de deepagents (app/main.py, que sigue siendo la
plantilla multiagente del repo): la tesis defiende un agente unico (seccion 2.4) y el
orquestador solo delegaba. Medido con scripts/medir_contexto.py, cada llamada del
subagente mandaba ~5000 tokens fijos (prompt + skills + 14 tools propias + 8 tools
internas de deepagents que el agente no usa: archivos, todo, task); este agente manda
~2000. Con ~12 llamadas por incidente, es la diferencia entre ~60 mil tokens y ~25 mil.

La seguridad no depende del framework: la politica, la lista de acciones, el kill switch
y la aprobacion humana (Ciclo.aprobar) las exige el dominio en cada ejecucion. Sin
`interrupt_on`, `ejecutar_remediacion_con_aprobacion` devuelve ERROR si nadie aprobo.
"""

from __future__ import annotations

from typing import Any

from app import loader


def _definicion(modelo: Any = None) -> Any:
    return loader.cargar_agente("aiops", modelo)


def modelo_por_defecto() -> str:
    """Modelo de agent.yaml: el que se usa si nadie eligio otro desde la UI."""
    return str(_definicion()["model"])


def construir(modelo: Any = None) -> Any:
    """`modelo`: un BaseChatModel ya armado (el de la UI) o None para el de agent.yaml."""
    from langchain.agents import create_agent

    definicion = _definicion(modelo)
    return create_agent(
        definicion["model"],
        definicion["tools"],
        system_prompt=definicion["system_prompt"],
        name="aiops",
    )
