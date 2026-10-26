"""Adaptador del loader generico (`rag:` en agent.yaml): busqueda sin filtro de servicio.
El agente aiops no lo usa; usa agents/aiops/conocimiento.py."""

from __future__ import annotations

from rag import store
from rag.embeddings import embed_consulta
from rag.types import SearchResult


def search(
    collection: str, query: str, k: int = 4, tenant_id: str | None = None
) -> list[SearchResult]:
    """`collection` y `tenant_id` se conservan por compatibilidad: el almacen ya no los usa."""
    pasajes = store.buscar(
        embed_consulta(query), servicio=None, k=k, min_sim=0.0, origenes=("repo", "subido")
    )
    return [SearchResult(p.contenido, f"C{p.id} {p.documento}", 1 - p.similitud) for p in pasajes]
