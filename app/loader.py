"""Descubre agentes en `agents/*/agent.yaml` y los convierte en `SubAgent` de deepagents.

Un agente nuevo se crea copiando `agents/_template/`. Este modulo no debe tocarse
para agregar agentes; si necesita cambiar para que un agente funcione, es una señal
de que ese agente pide algo fuera de lo que agent.yaml puede expresar.
"""

from __future__ import annotations

import importlib.util
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml
from deepagents import SubAgent

from infra import mcp as infra_mcp
from rag import retrieve as rag_retrieve

AGENTS_DIR = Path(__file__).resolve().parent.parent / "agents"


def _load_tool(agent_dir: Path, ref: str) -> Any:
    """Resuelve una referencia "modulo:funcion" contra los archivos del agente."""
    module_name, func_name = ref.split(":", 1)
    module_path = agent_dir / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(
        f"agents.{agent_dir.name}.{module_name}", module_path
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"No se pudo cargar {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, func_name)


def _load_skills(agent_dir: Path, skills_field: str | None) -> list[str]:
    """Lista las skills del agente: subcarpetas con SKILL.md dentro de `skills_field`.

    TODO(verificar): confirmar contra `reference.langchain.com/python/deepagents`
    si `SubAgent.skills` espera rutas de carpeta (una por skill) o rutas de
    archivo SKILL.md. Ver docs/open-questions.md.
    """
    if not skills_field:
        return []
    skills_dir = agent_dir / skills_field
    if not skills_dir.is_dir():
        return []
    return sorted(str(p.parent) for p in skills_dir.glob("*/SKILL.md"))


def _build_rag_tool(rag_field: dict[str, Any]) -> Callable[[str], str]:
    """Ver rag/README.md. `agent.yaml` solo declara `collection` (+ `k`
    opcional); la tool que llama a `rag.retrieve.search` la arma el loader."""
    collection = rag_field["collection"]
    k = rag_field.get("k", 4)

    def buscar_documentos(query: str) -> str:
        """Busca en la base documental de este agente y devuelve pasajes con su fuente.

        Usar para responder algo que dependa de un documento propio del dominio,
        no de conocimiento general. Cada resultado trae su `fuente`: si se cita
        en la respuesta, citar tambien esa fuente.
        """
        try:
            results = rag_retrieve.search(collection, query, k=k)
        except Exception as exc:  # sin embeddings/ingesta: el agente sigue sin RAG
            return f"Busqueda de documentos no disponible ({type(exc).__name__})."
        if not results:
            return "Sin resultados."
        return "\n\n".join(f"[fuente: {r.source}]\n{r.content}" for r in results)

    return buscar_documentos


def _build_subagent(agent_dir: Path, modelo_override: Any = None) -> SubAgent:
    config_path = agent_dir / "agent.yaml"
    config = yaml.safe_load(config_path.read_text())

    prompt_path = agent_dir / config["prompt"]
    system_prompt = prompt_path.read_text()

    tools = [_load_tool(agent_dir, ref) for ref in config.get("tools", [])]
    if rag_field := config.get("rag"):
        tools.append(_build_rag_tool(rag_field))
    if mcp_servers := config.get("mcp_servers"):
        tools.extend(infra_mcp.load_mcp_tools(mcp_servers))
    skills = _load_skills(agent_dir, config.get("skills"))
    require_approval = config.get("require_approval", [])

    subagent: SubAgent = {
        "name": config["name"],
        "description": config["description"],
        "system_prompt": system_prompt,
        "tools": tools,
    }
    if "model" in config:
        subagent["model"] = config["model"]
    if modelo_override is not None:
        # Modelo elegido desde la UI (infra/llm_config.py): pisa el de agent.yaml.
        subagent["model"] = modelo_override
    if skills:
        subagent["skills"] = skills
    if require_approval:
        subagent["interrupt_on"] = {tool: True for tool in require_approval}
    return subagent


def load_subagents(modelo_override: Any = None) -> list[SubAgent]:
    """Un `SubAgent` por cada `agents/<nombre>/agent.yaml`, salvo `_template`."""
    subagents = []
    for agent_dir in sorted(AGENTS_DIR.iterdir()):
        if not agent_dir.is_dir() or agent_dir.name.startswith("_"):
            continue
        if not (agent_dir / "agent.yaml").exists():
            continue
        subagents.append(_build_subagent(agent_dir, modelo_override))
    return subagents
