"""`domain/` y `rag/` no importan frameworks de agentes (regla 1). Un agente
nuevo puede usar deepagents/LangChain/LangGraph libremente en `agents/*/tools.py`,
pero no esta capa: si necesita algo del framework, esta en la capa equivocada."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FORBIDDEN_PREFIXES = ("deepagents", "langchain", "langgraph")
CHECKED_DIRS = ["domain", "rag"]


def _python_files() -> list[Path]:
    files: list[Path] = []
    for d in CHECKED_DIRS:
        files.extend((REPO_ROOT / d).rglob("*.py"))
    return files


def _forbidden_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [n.name for n in node.names if n.name.startswith(FORBIDDEN_PREFIXES)]
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module.startswith(FORBIDDEN_PREFIXES):
                found.append(node.module)
    return found


@pytest.mark.parametrize("path", _python_files(), ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_no_agent_framework_imports(path: Path) -> None:
    forbidden = _forbidden_imports(path)
    assert not forbidden, f"{path} importa framework de agentes: {forbidden}"
