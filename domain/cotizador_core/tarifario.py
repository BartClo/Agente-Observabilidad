"""Tabla de tarifas versionada por vigencia.

PLACEHOLDER - validar con experto en pricing/logistica. Los montos y fechas de
esta lista no representan tarifas reales de ningun operador; son solo datos de
ejemplo para el framework.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class TarifaVigente:
    zona: str
    vigente_desde: date
    vigente_hasta: date | None  # None = sigue vigente
    tarifa_base: float
    costo_por_kg: float


TARIFARIO: list[TarifaVigente] = [
    TarifaVigente("NORTE", date(2024, 1, 1), date(2025, 6, 30), 12_000.0, 2_500.0),
    TarifaVigente("NORTE", date(2025, 7, 1), None, 13_500.0, 2_800.0),
    TarifaVigente("CENTRO", date(2024, 1, 1), None, 8_000.0, 1_800.0),
    TarifaVigente("SUR", date(2024, 1, 1), date(2025, 12, 31), 15_000.0, 3_200.0),
    TarifaVigente("SUR", date(2026, 1, 1), None, 16_500.0, 3_500.0),
]


def tarifa_vigente(zona: str, fecha: date) -> TarifaVigente:
    candidatas = [
        t
        for t in TARIFARIO
        if t.zona == zona
        and t.vigente_desde <= fecha
        and (t.vigente_hasta is None or fecha <= t.vigente_hasta)
    ]
    if not candidatas:
        raise ValueError(f"Sin tarifa vigente para zona={zona!r} fecha={fecha}")
    if len(candidatas) > 1:
        raise ValueError(
            f"Tarifario inconsistente: mas de una vigencia activa para zona={zona!r} fecha={fecha}"
        )
    return candidatas[0]
