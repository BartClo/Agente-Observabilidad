"""Busqueda semantica sobre una collection ya ingerida."""

from __future__ import annotations

from rag import store
from rag.embeddings import embed_texts
from rag.types import SearchResult


def search(
    collection: str, query: str, k: int = 4, tenant_id: str | None = None
) -> list[SearchResult]:
    (query_embedding,) = embed_texts([query])
    return store.search(collection, query_embedding, k, tenant_id=tenant_id)
