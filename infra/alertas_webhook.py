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
from infra.perfil import Perfil


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


def _campo(item: Any, ruta: str) -> Any:
    valor = item
    for parte in ruta.split("."):
        valor = valor.get(parte) if isinstance(valor, dict) else None
    return valor


def _texto(valor: Any) -> str:
    return valor.strip() if isinstance(valor, str) else ""


def alertas_con_perfil(payload: dict[str, Any], perfil: Perfil) -> list[tuple[Alerta, bool]]:
    """Webhook de un ambiente con perfil: los campos salen del mapeo. El entorno lo fija el
    perfil, nunca el payload: quien pudiera enviar una alerta no debe poder decidir en que
    entorno se autoriza la accion. `lista` vacia: el payload es una sola alerta."""
    m = perfil.webhook
    crudo = _campo(payload, m.lista) if m.lista else [payload]
    if not isinstance(crudo, list):
        raise ValueError(f"el payload no trae una lista en {m.lista!r}")
    resultado: list[tuple[Alerta, bool]] = []
    for item in crudo:
        if not isinstance(item, dict):
            raise ValueError("cada alerta debe ser un objeto")
        ruta = m.servicio or f"labels.{perfil.etiqueta_servicio}"
        servicio = _texto(_campo(item, ruta))
        if not servicio and not m.servicio:
            servicio = _texto(_campo(item, "labels.job"))
        servicio = servicio or "desconocido"
        nombre = _texto(_campo(item, m.nombre)) or "desconocida"
        inicio = _texto(_campo(item, m.inicio))
        huella = _texto(_campo(item, m.huella)) or inicio
        crudo_sev = _texto(_campo(item, m.severidad))
        severidad = m.severidades.get(crudo_sev.lower()) or severidad_desde_label(crudo_sev)
        alerta = Alerta(
            id=f"{nombre}:{servicio}" + (f":{huella}" if huella else ""),
            nombre=nombre,
            servicio=servicio,
            entorno=perfil.entorno,
            severidad=severidad,
            resumen=_texto(_campo(item, m.resumen)),
            disparada_en=parse_timestamp_iso(inicio),
        )
        estado = _texto(_campo(item, m.estado)) or m.valor_firing
        resultado.append((alerta, estado == m.valor_firing))
    return resultado
