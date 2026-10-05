"""Compartido entre adaptadores de alertas (Prometheus pull en infra/observabilidad.py,
webhook push en infra/alertas_webhook.py): traducir severidad y parsear timestamps.
Extraido en la Fase 2 para no duplicar la logica que ya probo infra/observabilidad.py.
"""

from __future__ import annotations

from datetime import datetime

from domain.aiops_core.modelos import Severidad

# Grafana/Prometheus usan severity en ingles; el catalogo interno esta en espanol.
# Un valor no reconocido se trata como CRITICA (fail-safe: fuera del alcance
# autonomo, nunca se autoremedia por error). Ver docs/plan-aiops.md Fase 0.5.
SEVERIDAD_ALIAS: dict[str, Severidad] = {
    "critica": Severidad.CRITICA,
    "critical": Severidad.CRITICA,
    "alta": Severidad.ALTA,
    "high": Severidad.ALTA,
    "media": Severidad.MEDIA,
    "medium": Severidad.MEDIA,
    "warning": Severidad.MEDIA,
    "baja": Severidad.BAJA,
    "low": Severidad.BAJA,
    "info": Severidad.BAJA,
}


def severidad_desde_label(valor: str | None) -> Severidad:
    return SEVERIDAD_ALIAS.get((valor or "").strip().lower(), Severidad.CRITICA)


def parse_timestamp_iso(valor: str | None) -> float | None:
    """ISO 8601 (Prometheus/Alertmanager/Grafana: `activeAt`/`startsAt`) a epoch
    seconds. None si falta o no se puede parsear."""
    if not valor:
        return None
    try:
        return datetime.fromisoformat(valor.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None
