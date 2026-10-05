"""Puerto de persistencia de incidentes: lo unico que `Ciclo` sabe de como se guardan.

El adaptador concreto vive fuera de `domain/` (ver infra/incidentes_postgres.py). La
implementacion en memoria es el default de `Ciclo` y la que usan los tests y el banco
simulado: mismo comportamiento que antes de la Fase 1, sin perder nada.
"""

from __future__ import annotations

from typing import Protocol

from domain.aiops_core.modelos import Incidente


class RepositorioIncidentes(Protocol):
    def guardar(self, incidente: Incidente) -> None:
        """Crea o actualiza el incidente completo (upsert por `incidente.id`)."""
        ...

    def obtener(self, incidente_id: str) -> Incidente | None: ...

    def listar(self) -> list[Incidente]: ...


class RepositorioIncidentesMemoria:
    """Default de `Ciclo`: vive en el proceso, se pierde al reiniciar. Suficiente para
    tests, evals y el banco simulado; `infra.incidentes_postgres` la reemplaza cuando
    hay que sobrevivir a un reinicio (ver docs/plan-aiops.md Fase 1)."""

    def __init__(self) -> None:
        self._incidentes: dict[str, Incidente] = {}

    def guardar(self, incidente: Incidente) -> None:
        self._incidentes[incidente.id] = incidente

    def obtener(self, incidente_id: str) -> Incidente | None:
        return self._incidentes.get(incidente_id)

    def listar(self) -> list[Incidente]:
        return list(self._incidentes.values())
