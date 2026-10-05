"""Trocea texto en pedazos con solapamiento. Logica pura, sin dependencias externas."""

from __future__ import annotations

from rag.types import Chunk

DEFAULT_CHUNK_SIZE = 1000
DEFAULT_OVERLAP = 150


def chunk_text(
    text: str, source: str, size: int = DEFAULT_CHUNK_SIZE, overlap: int = DEFAULT_OVERLAP
) -> list[Chunk]:
    """Ventana deslizante por caracteres. No entiende de oraciones/parrafos: para
    algo mas fino (por ejemplo respetar limites de articulo legal), reemplazar
    esta funcion, no store.py ni ingest.py."""
    if size <= overlap:
        raise ValueError("size debe ser mayor que overlap")

    text = text.strip()
    if not text:
        return []

    chunks = []
    start = 0
    step = size - overlap
    while start < len(text):
        piece = text[start : start + size].strip()
        if piece:
            chunks.append(Chunk(content=piece, source=source))
        start += step
    return chunks
