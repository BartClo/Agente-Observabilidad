"""Mide el contexto FIJO que el agente le manda al LLM en cada llamada (prompt de sistema
+ esquemas de tools), para comparar arquitecturas sin gastar tokens: un LLM falso captura
la primera solicitud.

Importa porque ese contexto se reenvia completo en CADA vuelta del agente: el costo por
incidente es aproximadamente (llamadas x contexto fijo) + historial acumulado.

Arquitecturas:
  A. orquestador + subagente aiops (como corria hasta ahora): hay un orquestador que solo
     delega, y el subagente aparte.
  B. un unico deep agent con el prompt y las tools de aiops (sin orquestador).
  C. un unico agente de tool-calling de LangChain con las tools de aiops (sin las tools
     ni prompts internos de deepagents): agents/aiops/agente.py, el que usa el worker.

Uso: python -m scripts.medir_contexto
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.utils.function_calling import convert_to_openai_tool

from app import loader

_PEDIDO = "Atiende el incidente INC-X (alerta ServiceDown en checkout, entorno dev) hasta cerrarlo."

_mensajes: list[Any] = []
_tools: list[Any] = []


class Captura(GenericFakeChatModel):
    """Responde 'ok' una vez y deja constancia de lo que recibio."""

    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
        _tools.clear()
        _tools.extend(tools)
        return self

    def _generate(self, messages: list[Any], *args: Any, **kwargs: Any) -> Any:
        if not _mensajes:
            _mensajes.extend(messages)
        return super()._generate(messages, *args, **kwargs)


def _modelo() -> Captura:
    return Captura(messages=iter([AIMessage("ok")] * 5))


def _contar(texto: str) -> int:
    try:
        import tiktoken

        return len(tiktoken.get_encoding("cl100k_base").encode(texto))
    except Exception:  # sin tiktoken: ~4 caracteres por token
        return len(texto) // 4


def _medir(armar: Any) -> dict[str, int]:
    _mensajes.clear()
    _tools.clear()
    agente = armar(_modelo())
    agente.invoke({"messages": [{"role": "user", "content": _PEDIDO}]})
    sistema = "\n".join(str(m.content) for m in _mensajes if m.type == "system")
    esquemas = json.dumps([convert_to_openai_tool(t) for t in _tools], ensure_ascii=False)
    return {
        "tools": len(_tools),
        "tokens_sistema": _contar(sistema),
        "tokens_tools": _contar(esquemas),
        "tokens_total": _contar(sistema) + _contar(esquemas) + _contar(_PEDIDO),
    }


def _aiops() -> dict[str, Any]:
    return dict(loader._build_subagent(Path(loader.AGENTS_DIR) / "aiops"))


def arquitectura_a(modelo: Any) -> Any:
    from app.main import build_agent

    return build_agent(modelo)


def arquitectura_b(modelo: Any) -> Any:
    from deepagents import create_deep_agent

    sub = _aiops()
    return create_deep_agent(
        model=modelo,
        system_prompt=sub["system_prompt"],
        tools=sub["tools"],
        skills=sub.get("skills"),
        interrupt_on=sub.get("interrupt_on"),
    )


def arquitectura_c(modelo: Any) -> Any:
    from agents.aiops.agente import construir

    return construir(modelo)  # el que corre el worker


def main() -> None:
    filas = []
    for nombre, armar in (
        ("A orquestador + subagente (llamada del orquestador)", arquitectura_a),
        ("B deep agent unico", arquitectura_b),
        ("C agente de tool-calling unico", arquitectura_c),
    ):
        try:
            filas.append((nombre, _medir(armar)))
        except Exception as exc:
            filas.append((nombre, {"error": f"{type(exc).__name__}: {exc}"}))  # type: ignore[dict-item]
    print("| Arquitectura | Tools | Tokens sistema | Tokens tools | Total por llamada |")
    print("|---|---|---|---|---|")
    for nombre, m in filas:
        if "error" in m:
            print(f"| {nombre} | error: {m['error']} | | | |")
        else:
            print(
                f"| {nombre} | {m['tools']} | {m['tokens_sistema']} | {m['tokens_tools']} "
                f"| **{m['tokens_total']}** |"
            )


if __name__ == "__main__":
    main()
