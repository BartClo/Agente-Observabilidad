"""El bloque `rag:` de agent.yaml agrega sola la tool `buscar_documentos`,
sin tocar tools.py. No pega a Postgres ni a OpenAI: mockea rag.retrieve.search."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest

from app import loader
from rag import retrieve as rag_retrieve
from rag.types import SearchResult


@pytest.fixture
def agent_with_rag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    agents_root = tmp_path / "agents"
    agents_root.mkdir()
    agent_dir = agents_root / "hello"
    shutil.copytree(Path(__file__).resolve().parent.parent / "agents" / "_template", agent_dir)

    agent_yaml = agent_dir / "agent.yaml"
    agent_yaml.write_text(agent_yaml.read_text() + "\nrag:\n  collection: demo\n  k: 2\n")

    monkeypatch.setattr(loader, "AGENTS_DIR", agents_root)
    return agents_root


def test_rag_tool_gets_added_when_configured(
    agent_with_rag: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    called_with: dict[str, object] = {}

    def fake_search(
        collection: str, query: str, k: int = 4, tenant_id: str | None = None
    ) -> list[SearchResult]:
        called_with.update(collection=collection, query=query, k=k)
        return [SearchResult(content="contenido", source="doc.md", distance=0.1)]

    monkeypatch.setattr(rag_retrieve, "search", fake_search)

    subagents = loader.load_subagents()
    assert len(subagents) == 1
    tools = cast("list[Callable[..., str]]", subagents[0]["tools"])
    tool_names = [t.__name__ for t in tools]
    assert "buscar_documentos" in tool_names

    buscar = next(t for t in tools if t.__name__ == "buscar_documentos")
    output = buscar("pregunta de prueba")

    assert called_with == {"collection": "demo", "query": "pregunta de prueba", "k": 2}
    assert "doc.md" in output
    assert "contenido" in output
