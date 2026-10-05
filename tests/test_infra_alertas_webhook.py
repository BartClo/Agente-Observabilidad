"""Parseo del payload de Grafana. Sin red ni Postgres: unitario puro."""

from __future__ import annotations

from domain.aiops_core.modelos import Severidad
from infra.alertas_webhook import alerta_desde_grafana


def test_firing_con_fingerprint_y_severidad_en_ingles() -> None:
    item = {
        "status": "firing",
        "labels": {
            "alertname": "ServiceDown",
            "service": "checkout",
            "env": "staging",
            "severity": "critical",
        },
        "annotations": {"summary": "caido"},
        "startsAt": "2026-10-05T10:00:00Z",
        "fingerprint": "abc123",
    }
    alerta, es_firing = alerta_desde_grafana(item, "service")
    assert es_firing is True
    assert alerta.id == "ServiceDown:checkout:abc123"
    assert alerta.servicio == "checkout"
    assert alerta.entorno == "staging"
    assert alerta.severidad is Severidad.CRITICA
    assert alerta.resumen == "caido"
    assert alerta.disparada_en is not None


def test_resolved_sin_fingerprint_usa_startsat_como_disambiguador() -> None:
    item = {
        "status": "resolved",
        "labels": {"alertname": "DiskUsageHigh", "service": "billing"},
        "startsAt": "2026-10-05T11:00:00Z",
    }
    alerta, es_firing = alerta_desde_grafana(item, "service")
    assert es_firing is False
    assert alerta.id == "DiskUsageHigh:billing:2026-10-05T11:00:00Z"


def test_dos_disparos_de_la_misma_alerta_dan_ids_distintos() -> None:
    base = {"labels": {"alertname": "ServiceDown", "service": "checkout"}, "status": "firing"}
    a1, _ = alerta_desde_grafana({**base, "fingerprint": "f1"}, "service")
    a2, _ = alerta_desde_grafana({**base, "fingerprint": "f2"}, "service")
    assert a1.id != a2.id


def test_etiqueta_de_servicio_configurable_y_defaults() -> None:
    item = {"labels": {"alertname": "X", "mi_etiqueta": "svc"}, "status": "firing"}
    alerta, _ = alerta_desde_grafana(item, "mi_etiqueta")
    assert alerta.servicio == "svc"
    assert alerta.entorno == "desconocido"
    assert alerta.severidad is Severidad.CRITICA  # severity ausente: fail-safe
