"""El bloque `mcp_servers:` de agent.yaml agrega las tools de esos servidores.
No levanta ningun servidor MCP real: mockea infra.mcp.load_mcp_tools."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest
from langchain_core.tools import tool

from app import loader
from infra import mcp as infra_mcp


@pytest.fixture
def agent_with_mcp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    agents_root = tmp_path / "agents"
    agents_root.mkdir()
    agent_dir = agents_root / "hello"
    shutil.copytree(Path(__file__).resolve().parent.parent / "agents" / "_template", agent_dir)

    agent_yaml = agent_dir / "agent.yaml"
    agent_yaml.write_text(
        agent_yaml.read_text()
        + "\nmcp_servers:\n  demo:\n    transport: stdio\n    command: python\n    args: []\n"
    )

    monkeypatch.setattr(loader, "AGENTS_DIR", agents_root)
    return agents_root


def test_mcp_tools_get_added_when_configured(
    agent_with_mcp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    @tool
    def herramienta_remota(x: str) -> str:
        """Tool falsa que simula venir de un servidor MCP."""
        return f"echo {x}"

    seen_servers: dict[str, Any] = {}

    def fake_load_mcp_tools(servers: dict[str, Any]) -> list[Any]:
        seen_servers.update(servers)
        return [herramienta_remota]

    monkeypatch.setattr(infra_mcp, "load_mcp_tools", fake_load_mcp_tools)

    subagents = loader.load_subagents()
    assert len(subagents) == 1
    tools = cast("list[Callable[..., Any]]", subagents[0]["tools"])
    tool_names = [getattr(t, "name", getattr(t, "__name__", None)) for t in tools]

    assert "herramienta_remota" in tool_names
    assert seen_servers == {"demo": {"transport": "stdio", "command": "python", "args": []}}
