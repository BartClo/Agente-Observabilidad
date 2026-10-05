"""Adaptador Prometheus + Loki para `domain.aiops_core.observabilidad.ObservabilidadPort`.

Solo HTTP de lectura (stdlib, sin dependencias nuevas). Las consultas PromQL y las
etiquetas son supuestos razonables (node_exporter, kube-state-metrics, rabbitmq,
blackbox_exporter): hay que ajustarlas a las metricas reales del entorno, pasando
`consultas` o `etiqueta_servicio`. Ver docs/open-questions.md.
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from collections.abc import Mapping
from typing import Any

from domain.aiops_core.acciones import validar_servicio
from domain.aiops_core.modelos import Alerta, Severidad

# Grafana/Prometheus usan severity en ingles; el catalogo interno esta en espanol.
# Un valor no reconocido se trata como CRITICA (fail-safe: fuera del alcance
# autonomo, nunca se autoremedia por error). Ver docs/plan-aiops.md Fase 0.5.
_SEVERIDAD_ALIAS: dict[str, Severidad] = {
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


def _severidad_desde_label(valor: str | None) -> Severidad:
    return _SEVERIDAD_ALIAS.get((valor or "").strip().lower(), Severidad.CRITICA)

# metrica del catalogo -> PromQL. `{s}` se reemplaza por el servicio ya validado;
# `{l}` por la etiqueta que identifica el servicio (AIOPS_SERVICE_LABEL, "job" por
# defecto: la misma etiqueta que usan alertas_activas()/logs(), no una fija distinta).
CONSULTAS_POR_DEFECTO: dict[str, str] = {
    "up": 'max(up{{{l}="{s}"}})',
    "disk_usage_percent": (
        '100 * max(1 - node_filesystem_avail_bytes{{{l}="{s}",mountpoint="/"}}'
        ' / node_filesystem_size_bytes{{{l}="{s}",mountpoint="/"}})'
    ),
    "pod_ready": 'sum(kube_pod_status_ready{{condition="true",pod=~"{s}-.*"}})',
    "queue_consumers_active": 'sum(rabbitmq_queue_consumers{{queue="{s}"}})',
    "cert_days_remaining": ('(min(probe_ssl_earliest_cert_expiry{{{l}="{s}"}}) - time()) / 86400'),
}


class PrometheusLoki:
    def __init__(
        self,
        prometheus_url: str,
        loki_url: str | None = None,
        consultas: Mapping[str, str] | None = None,
        etiqueta_servicio: str = "service",
        timeout_s: float = 10.0,
    ) -> None:
        self._prom = prometheus_url.rstrip("/")
        self._loki = loki_url.rstrip("/") if loki_url else None
        self._consultas = dict(consultas or CONSULTAS_POR_DEFECTO)
        self._etiqueta = etiqueta_servicio
        self._timeout = timeout_s

    @classmethod
    def desde_entorno(cls) -> PrometheusLoki:
        return cls(
            prometheus_url=os.environ["AIOPS_PROMETHEUS_URL"],
            loki_url=os.environ.get("AIOPS_LOKI_URL") or None,
            etiqueta_servicio=os.environ.get("AIOPS_SERVICE_LABEL", "service"),
        )

    def _get(self, url: str) -> Any:
        with urllib.request.urlopen(url, timeout=self._timeout) as resp:  # noqa: S310
            return json.loads(resp.read().decode())

    def alertas_activas(self) -> list[Alerta]:
        datos = self._get(f"{self._prom}/api/v1/alerts")
        alertas = []
        for a in datos.get("data", {}).get("alerts", []):
            if a.get("state") != "firing":
                continue
            labels = a.get("labels", {})
            servicio = labels.get(self._etiqueta) or labels.get("job", "desconocido")
            nombre = labels.get("alertname", "desconocida")
            severidad = _severidad_desde_label(labels.get("severity"))
            alertas.append(
                Alerta(
                    id=f"{nombre}:{servicio}",
                    nombre=nombre,
                    servicio=servicio,
                    entorno=labels.get("env", labels.get("environment", "desconocido")),
                    severidad=severidad,
                    resumen=a.get("annotations", {}).get("summary", ""),
                )
            )
        return alertas

    def metrica(self, servicio: str, nombre: str) -> float | None:
        plantilla = self._consultas.get(nombre)
        if plantilla is None:
            return None
        query = plantilla.format(s=validar_servicio(servicio), l=self._etiqueta)
        url = f"{self._prom}/api/v1/query?" + urllib.parse.urlencode({"query": query})
        resultado = self._get(url).get("data", {}).get("result", [])
        if not resultado:
            return None  # sin datos = sin evidencia
        return float(resultado[0]["value"][1])

    def logs(self, servicio: str, lineas: int) -> list[str]:
        if self._loki is None:
            return []
        query = f'{{{self._etiqueta}="{validar_servicio(servicio)}"}}'
        params = urllib.parse.urlencode(
            {"query": query, "limit": lineas, "start": int((time.time() - 3600) * 1e9)}
        )
        datos = self._get(f"{self._loki}/loki/api/v1/query_range?{params}")
        return [
            linea
            for stream in datos.get("data", {}).get("result", [])
            for _, linea in stream.get("values", [])
        ][:lineas]
