"""Embeddings con Gemini (REST). Si se cambia de proveedor, este es el unico archivo a
tocar (store.py/ingest.py no saben de Gemini). La key sale de las credenciales cifradas
de la UI, nunca de .env."""

from __future__ import annotations

import json
import math
import os
import time
import urllib.request
from typing import Any

EMBEDDING_MODEL = os.environ.get("RAG_EMBEDDING_MODEL", "gemini-embedding-001")
# Debe coincidir con `embedding vector(N)` de la migracion de rag_chunks.
EMBEDDING_DIM = int(os.environ.get("RAG_EMBEDDING_DIM", "1536"))
_URL = "https://generativelanguage.googleapis.com/v1beta/models/{m}:batchEmbedContents"
_LOTE = 100
_INTENTOS = 3
_TIMEOUT_S = 20


class ErrorEmbeddings(Exception):
    """Gemini no respondio o no hay key. El conocimiento nunca bloquea un incidente."""


def _key() -> str:
    from infra.llm_config import ConfigLLMError, api_key

    try:
        return api_key("google")
    except ConfigLLMError as exc:
        raise ErrorEmbeddings(str(exc)) from exc


def _post(url: str, cuerpo: dict[str, Any], key: str) -> dict[str, Any]:
    req = urllib.request.Request(  # noqa: S310
        url,
        data=json.dumps(cuerpo).encode(),
        headers={"Content-Type": "application/json", "x-goog-api-key": key},
    )
    with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as r:  # noqa: S310
        return json.load(r)  # type: ignore[no-any-return]


def _normalizar(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def _embed(textos: list[str], tarea: str) -> list[list[float]]:
    key = _key()
    url = _URL.format(m=EMBEDDING_MODEL)
    salida: list[list[float]] = []
    for i in range(0, len(textos), _LOTE):
        cuerpo = {
            "requests": [
                {
                    "model": f"models/{EMBEDDING_MODEL}",
                    "content": {"parts": [{"text": t}]},
                    "taskType": tarea,
                    "outputDimensionality": EMBEDDING_DIM,
                }
                for t in textos[i : i + _LOTE]
            ]
        }
        resp: dict[str, Any] = {}
        for intento in range(_INTENTOS):
            try:
                resp = _post(url, cuerpo, key)
                break
            except Exception as exc:
                if intento == _INTENTOS - 1:
                    # solo el tipo: el mensaje original puede traer la key en la URL o cabecera
                    raise ErrorEmbeddings(f"Gemini no respondio ({type(exc).__name__})") from None
                time.sleep(2**intento)
        salida += [_normalizar(e["values"]) for e in resp["embeddings"]]
    return salida


def embed_documentos(textos: list[str]) -> list[list[float]]:
    return _embed(textos, "RETRIEVAL_DOCUMENT") if textos else []


def embed_consulta(texto: str) -> list[float]:
    return _embed([texto], "RETRIEVAL_QUERY")[0]


# Alias transitorio: ingest.py/retrieve.py viejos lo usan hasta que las tareas 3 y 4 los
# reemplacen.
embed_texts = embed_documentos
