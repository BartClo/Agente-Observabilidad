"""Tipos compartidos del componente RAG. Sin dependencias de frameworks de agentes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Documento:
    """Metadatos de un documento indexado. `servicios` vacio = general (aplica a todos)."""

    nombre: str
    origen: str  # "repo" (versionado) | "subido" (cargado por un administrador)
    servicios: tuple[str, ...]
    tipo: str  # ficha | arquitectura | postmortem | guia | runbook | otro
    vigente_desde: date | None
    obsoleto: bool
    sha256: str
    paginas: int | None
    bytes_: int | None
    subido_por: str | None


@dataclass(frozen=True)
class Fragmento:
    """Un pedazo de texto listo para embeber; `pagina` solo existe en los PDF."""

    contenido: str
    pagina: int | None
    orden: int


@dataclass(frozen=True)
class Pasaje:
    """Un resultado de busqueda. `id` es lo que se cita como C<id>."""

    id: int
    documento: str
    pagina: int | None
    contenido: str
    similitud: float
    vigente_desde: date | None


@dataclass(frozen=True)
class SearchResult:
    """Contrato del loader generico (`rag:` en agent.yaml): contenido, fuente, distancia."""

    content: str
    source: str
    distance: float
