"""Puerto de observabilidad: lo unico que el ciclo sabe de Prometheus/Loki/Datadog.

Los adaptadores concretos viven fuera de `domain/` (ver infra/observabilidad.py y
`simulador.py` para el banco experimental).
"""

from __future__ import annotations

from typing import Protocol

from domain.aiops_core.modelos import Alerta


class ObservabilidadPort(Protocol):
    def alertas_activas(self) -> list[Alerta]: ...

    def metrica(self, servicio: str, nombre: str) -> float | None:
        """Valor actual de la metrica, o None si no hay dato (sin evidencia)."""
        ...

    def logs(self, servicio: str, lineas: int) -> list[str]: ...
