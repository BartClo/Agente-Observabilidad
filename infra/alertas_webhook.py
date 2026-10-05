"""Convierte un item de alerta del payload webhook de Grafana (contact point tipo
webhook, formato Alertmanager-compatible) en `domain.aiops_core.modelos.Alerta`.

No implementa `ObservabilidadPort`: a diferencia de infra/observabilidad.py (pull,
`alertas_activas()` lista lo que hay), esto es push -- cada llamado del webhook trae
una alerta ya completa. `Ciclo.abrir_desde_alerta`/`notificar_resuelta_en_origen` (ver
domain/aiops_core/ciclo.py) la reciben directamente, sin pasar por ningun adaptador de
"listado". Ver docs/plan-aiops.md Fase 2.
"""

from __future__ import annotations

from typing import Any

from domain.aiops_core.modelos import Alerta
from infra.alertas_comun import parse_timestamp_iso, severidad_desde_label


def alerta_desde_grafana(item: dict[str, Any], etiqueta_servicio: str) -> tuple[Alerta, bool]:
    """Devuelve `(alerta, es_firing)`. `es_firing=False` es un `status: resolved`.

    El id incluye `fingerprint` (o `startsAt` si falta) para que cada disparo real
    sea distinto, igual que infra/observabilidad.py con `activeAt` (ver Fase 0.5):
    sin esto, reintentos del webhook de Grafana para la misma alerta colisionarian
    con un incidente ya cerrado."""
    labels = item.get("labels", {})
    anotaciones = item.get("annotations", {})
    servicio = labels.get(etiqueta_servicio) or labels.get("job", "desconocido")
    nombre = labels.get("alertname", "desconocida")
    disparada_en = parse_timestamp_iso(item.get("startsAt"))
    disambiguador = item.get("fingerprint") or item.get("startsAt") or ""
    sufijo = f":{disambiguador}" if disambiguador else ""
    alerta = Alerta(
        id=f"{nombre}:{servicio}{sufijo}",
        nombre=nombre,
        servicio=servicio,
        entorno=labels.get("env", labels.get("environment", "desconocido")),
        severidad=severidad_desde_label(labels.get("severity")),
        resumen=anotaciones.get("summary", ""),
        disparada_en=disparada_en,
    )
    return alerta, item.get("status", "firing") == "firing"
