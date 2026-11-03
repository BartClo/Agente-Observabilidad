"""Congela el agente antes del experimento final: registra el commit, el modelo, el
agente, el umbral y los hashes del prompt y de los runbooks en resultados/congelado.json.
Las corridas `--fase final` de scripts/experimento.py se niegan a correr si el codigo
cambio despues. Solo stdlib: corre en el host, con el laboratorio levantado.

    python -m scripts.congelar
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Any

from scripts.experimento import AISLAMIENTO, CONFIG_RAG, RAG

RAIZ = Path(__file__).resolve().parent.parent
API = os.environ.get("EXP_API", "http://localhost:8010")
RUTA = RAIZ / "resultados" / "congelado.json"


def _git(*args: str) -> str:
    resultado = subprocess.run(["git", *args], cwd=RAIZ, capture_output=True, text=True, check=True)
    return resultado.stdout.strip()


def _sha256(*rutas: Path) -> str:
    h = hashlib.sha256()
    for ruta in sorted(rutas):
        h.update(ruta.name.encode())
        h.update(ruta.read_bytes())
    return h.hexdigest()


def _env(clave: str, defecto: str = "") -> str:
    if valor := os.environ.get(clave):
        return valor
    archivo = RAIZ / ".env"
    if archivo.exists():
        for linea in archivo.read_text(encoding="utf-8").splitlines():
            if linea.startswith(f"{clave}="):
                return linea.split("=", 1)[1].strip() or defecto
    return defecto


def _config_llm() -> dict[str, Any]:
    token = _env("AIOPS_ADMIN_TOKEN").split(",")[0].strip()
    req = urllib.request.Request(  # noqa: S310
        f"{API}/config/llm", headers={"Authorization": f"Bearer {token}"}
    )
    with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310
        return dict(json.load(r))


def construir_registro() -> dict[str, object]:
    if _git("status", "--porcelain", "--untracked-files=no"):
        raise SystemExit("Hay cambios sin commitear: commitear antes de congelar")
    cfg = _config_llm()
    if cfg["respaldo"]["proveedor"]:
        raise SystemExit(
            "Hay un modelo de respaldo configurado: quitarlo. Un incidente atendido por dos "
            "modelos no es atribuible a ninguno"
        )
    activo = cfg["activo"]
    if not activo["proveedor"]:
        raise SystemExit("No hay modelo elegido en la UI: elegir el modelo del experimento")
    return {
        "fecha": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "commit": _git("rev-parse", "HEAD"),
        "modelo": f"{activo['proveedor']}:{activo['modelo']}",
        "agente": os.environ.get("AIOPS_AGENTE", "unico"),
        "umbral_confianza": _env("AIOPS_CONFIDENCE_THRESHOLD", "0.8"),
        # consultar_eventos (estado y eventos del pod): "0" la quita, brazo sin investigacion
        "investigacion": _env("AIOPS_INVESTIGACION", "1"),
        # lo que el experimento fija en cada corrida (ver experimento.AISLAMIENTO)
        "aislamiento_entre_corridas": dict(AISLAMIENTO),
        "prompt_sha256": _sha256(RAIZ / "agents" / "aiops" / "prompt.md"),
        "runbooks_sha256": _sha256(*(RAIZ / "agents" / "aiops" / "runbooks").glob("RB-*.md")),
        # Base de conocimiento: el corpus versionado (lo unico que entra en lo medido), el
        # modelo de embeddings y los parametros de busqueda. Cambiar un documento cambia el hash.
        "rag": {
            "activo": RAG,
            "embedding_modelo": _env("AIOPS_EMBEDDING_MODEL", "gemini-embedding-001"),
            "config": {**CONFIG_RAG, "AIOPS_RAG_ORIGENES": AISLAMIENTO["AIOPS_RAG_ORIGENES"]},
            "corpus_sha256": _sha256(*(RAIZ / "corpus").glob("*.md")),
        },
    }


def main() -> int:
    registro = construir_registro()
    RUTA.parent.mkdir(parents=True, exist_ok=True)
    RUTA.write_text(json.dumps(registro, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Congelado en {RUTA}:\n{json.dumps(registro, indent=2, ensure_ascii=False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
