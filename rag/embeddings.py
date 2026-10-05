"""Cliente de embeddings. OpenAI hoy; si se cambia de proveedor, este es el
unico archivo a tocar (store.py/retrieve.py/ingest.py no saben de OpenAI)."""

from __future__ import annotations

import os

from openai import OpenAI

EMBEDDING_MODEL = os.environ.get("RAG_EMBEDDING_MODEL", "text-embedding-3-small")
# Dimension del modelo default. Si se cambia RAG_EMBEDDING_MODEL a uno con otra
# dimension, hay que migrar la columna `embedding vector(N)` en store.py.
EMBEDDING_DIM = 1536

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    return _client


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    response = _get_client().embeddings.create(model=EMBEDDING_MODEL, input=texts)
    return [item.embedding for item in response.data]
