"""Trocea texto en fragmentos con solapamiento. Logica pura, sin dependencias externas."""

from __future__ import annotations

from rag.types import Fragmento

DEFAULT_CHUNK_SIZE = 700
DEFAULT_OVERLAP = 100


def fragmentar(
    paginas: list[tuple[int | None, str]],
    size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_OVERLAP,
) -> list[Fragmento]:
    """Ventana deslizante por caracteres, pagina por pagina (un fragmento nunca cruza de
    pagina, asi la cita `p.N` es exacta). `orden` numera los fragmentos del documento.
    No entiende de oraciones: para algo mas fino, reemplazar esta funcion."""
    if size <= overlap:
        raise ValueError("size debe ser mayor que overlap")
    fragmentos: list[Fragmento] = []
    step = size - overlap
    for pagina, texto in paginas:
        texto = texto.strip()
        for start in range(0, len(texto), step):
            pieza = texto[start : start + size].strip()
            if pieza:
                fragmentos.append(Fragmento(pieza, pagina, len(fragmentos)))
            if start + size >= len(texto):
                break
    return fragmentos
