"""Tipos compartidos del componente RAG. Sin dependencias de frameworks de agentes."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Chunk:
    """Un pedazo de texto listo para embeber y guardar."""

    content: str
    source: str


@dataclass(frozen=True)
class SearchResult:
    """Un resultado de busqueda: el chunk mas la distancia contra la query."""

    content: str
    source: str
    distance: float
