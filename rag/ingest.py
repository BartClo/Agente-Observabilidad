"""Ingesta de archivos de texto a una collection. Formatos: .txt y .md."""

from __future__ import annotations

from pathlib import Path

from rag import store
from rag.chunking import chunk_text
from rag.embeddings import embed_texts

SUPPORTED_SUFFIXES = {".txt", ".md"}


def ingest_path(collection: str, path: Path, tenant_id: str = "default") -> int:
    """Ingiere un archivo o, si `path` es directorio, todos los .txt/.md debajo.

    Devuelve la cantidad de chunks guardados.
    """
    files = [path] if path.is_file() else sorted(
        p for p in path.rglob("*") if p.suffix in SUPPORTED_SUFFIXES
    )

    total = 0
    for file in files:
        chunks = chunk_text(file.read_text(), source=str(file.relative_to(path.parent)))
        if not chunks:
            continue
        embeddings = embed_texts([c.content for c in chunks])
        total += store.upsert_chunks(collection, tenant_id, chunks, embeddings)
    return total
