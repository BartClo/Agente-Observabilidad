"""Prueba end-to-end del loader: copiar _template (como pide el flujo real de
"crear un agente") y verificar que se convierte en un SubAgent usable, sin
tocar app/."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest

from app import loader

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "agents" / "_template"


@pytest.fixture
def hello_agents_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    agents_root = tmp_path / "agents"
    agents_root.mkdir()
    shutil.copytree(TEMPLATE_DIR, agents_root / "hello")
    monkeypatch.setattr(loader, "AGENTS_DIR", agents_root)
    return agents_root


def test_template_is_not_loaded_directly() -> None:
    subagents = loader.load_subagents()
    names = [s["name"] for s in subagents]
    assert "template" not in names


def test_copied_template_loads_as_subagent(hello_agents_dir: Path) -> None:
    subagents = loader.load_subagents()

    assert len(subagents) == 1
    subagent = subagents[0]
    assert subagent["name"] == "template"
    assert "system_prompt" in subagent and subagent["system_prompt"]
    assert len(subagent["tools"]) == 1
    say_hello = cast(Callable[[str], str], subagent["tools"][0])
    assert say_hello("mundo") == "Hola, mundo. Soy el agente plantilla."
    assert subagent["skills"] == [str(hello_agents_dir / "hello" / "skills" / "example")]
