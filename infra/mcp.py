"""Conexion generica a servidores MCP via langchain-mcp-adapters. No decide que
hace un agente con las tools que trae un servidor: solo las conecta. Ver
infra/README.md para el formato de `mcp_servers` en agent.yaml."""

from __future__ import annotations

import asyncio
from typing import Any

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient


async def _load_mcp_tools_async(servers: dict[str, dict[str, Any]]) -> list[BaseTool]:
    # `servers` viene de un `agent.yaml` sin tipar; confiamos en que cada entrada
    # respeta la forma de StdioConnection/SSEConnection/etc en tiempo de ejecucion.
    client = MultiServerMCPClient(servers)  # type: ignore[arg-type]
    return await client.get_tools()


def load_mcp_tools(servers: dict[str, dict[str, Any]]) -> list[BaseTool]:
    """Version sincrona, para usar en el arranque (app/loader.py). Dentro de un
    grafo LangGraph ya corriendo, usar `MultiServerMCPClient` async directo."""
    return asyncio.run(_load_mcp_tools_async(servers))
