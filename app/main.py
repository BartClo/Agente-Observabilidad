"""Punto de entrada: arma el Deep Agent orquestador con los subagentes de `agents/`.

Agregar un agente nuevo no toca este archivo (ver app/loader.py).
"""

from __future__ import annotations

import os
from typing import Any

from deepagents import create_deep_agent

from app.loader import load_subagents

ORCHESTRATOR_MODEL = os.environ.get("ORCHESTRATOR_MODEL", "anthropic:claude-sonnet-5")

ORCHESTRATOR_PROMPT = """\
Sos el agente orquestador. No resolves nada vos mismo: delegas cada pedido al
subagente cuyo `description` calce mejor. Si ninguno calza, decilo en vez de
improvisar una respuesta.
"""


def build_agent() -> Any:
    return create_deep_agent(
        model=ORCHESTRATOR_MODEL,
        system_prompt=ORCHESTRATOR_PROMPT,
        subagents=load_subagents(),
    )


if __name__ == "__main__":
    agent = build_agent()
    result = agent.invoke(
        {"messages": [{"role": "user", "content": "hola, quien sos?"}]}
    )
    print(result["messages"][-1].content)
