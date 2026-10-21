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


def modelo_de_la_ui() -> tuple[Any, str] | None:
    """(modelo, "proveedor:modelo") elegido desde la UI (infra/llm_config.py), o None si
    no hay uno elegido o no hay base de datos: en ese caso se usa el modelo por defecto."""
    if not os.environ.get("DATABASE_URL"):
        return None
    from infra.llm_config import modelo_activo

    return modelo_activo()


def respaldo_de_la_ui() -> tuple[Any, str] | None:
    """Modelo de respaldo elegido en la UI, o None. Un respaldo mal configurado (key que
    ya no se puede descifrar, p. ej.) nunca debe impedir atender el incidente."""
    if not os.environ.get("DATABASE_URL"):
        return None
    from infra.llm_config import ConfigLLMError, modelo_respaldo

    try:
        return modelo_respaldo()
    except ConfigLLMError:
        return None


def build_agent(modelo: Any = None) -> Any:
    """`modelo`: un BaseChatModel ya armado (p. ej. el de modelo_de_la_ui()). Lo usan el
    orquestador y todos los subagentes. Sin modelo, cada uno usa el suyo por defecto
    (ORCHESTRATOR_MODEL y el `model` de cada agent.yaml), como antes."""
    return create_deep_agent(
        model=modelo or ORCHESTRATOR_MODEL,
        system_prompt=ORCHESTRATOR_PROMPT,
        subagents=load_subagents(modelo_override=modelo),
    )


if __name__ == "__main__":
    agent = build_agent()
    result = agent.invoke({"messages": [{"role": "user", "content": "hola, quien sos?"}]})
    print(result["messages"][-1].content)
