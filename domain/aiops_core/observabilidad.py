"""Puerto de observabilidad: lo unico que el ciclo sabe de Prometheus/Loki/Datadog.

Los adaptadores concretos viven fuera de `domain/` (ver infra/observabilidad.py y
`simulador.py` para el banco experimental).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from domain.aiops_core.modelos import Alerta


class ObservabilidadPort(Protocol):
    def alertas_activas(self) -> list[Alerta]: ...

    def metrica(self, servicio: str, nombre: str) -> float | None:
        """Valor actual de la metrica, o None si no hay dato (sin evidencia)."""
        ...

    def logs(self, servicio: str, lineas: int, desde: float | None = None) -> list[str]:
        """Ultimas lineas de log del servicio. `desde` (epoch s) acota la ventana; sin el,
        cada adaptador usa la suya (Loki: la ultima hora)."""
        ...


@runtime_checkable
class InvestigacionPort(Protocol):
    """Evidencia de solo lectura sobre las cargas de un servicio (estado y eventos del
    orquestador). Es opcional: sin ella el agente investiga con metricas y logs."""

    def eventos(self, servicio: str, maximo: int) -> list[str]:
        """Estado de los contenedores y ultimos eventos del servicio, una linea cada uno.
        Lanza RuntimeError/OSError si no puede consultar."""
        ...
