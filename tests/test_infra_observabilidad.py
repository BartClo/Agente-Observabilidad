"""Adaptador Prometheus/Loki con HTTP falso: valida el parseo y que el servicio se
valide antes de interpolarlo en PromQL/LogQL."""

from __future__ import annotations

from typing import Any

import pytest

from domain.aiops_core.acciones import AccionNoPermitida
from domain.aiops_core.modelos import Severidad
from infra.observabilidad import PrometheusLoki


class Falso(PrometheusLoki):
    def __init__(self, respuestas: dict[str, Any], **kw: Any) -> None:
        super().__init__("http://prom:9090", "http://loki:3100", **kw)
        self.respuestas = respuestas
        self.urls: list[str] = []

    def _get(self, url: str) -> Any:
        self.urls.append(url)
        for clave, valor in self.respuestas.items():
            if clave in url:
                return valor
        return {}


def test_alertas_solo_firing_y_severidad_tolerante() -> None:
    obs = Falso(
        {
            "/api/v1/alerts": {
                "data": {
                    "alerts": [
                        {
                            "state": "firing",
                            "labels": {
                                "alertname": "ServiceDown",
                                "service": "checkout",
                                "env": "staging",
                                "severity": "alta",
                            },
                            "annotations": {"summary": "caido"},
                        },
                        {"state": "firing", "labels": {"alertname": "X", "severity": "warning"}},
                        {"state": "pending", "labels": {"alertname": "Y"}},
                    ]
                }
            }
        }
    )
    alertas = obs.alertas_activas()
    assert [a.id for a in alertas] == ["ServiceDown:checkout", "X:desconocido"]
    assert alertas[0].severidad is Severidad.ALTA and alertas[0].entorno == "staging"
    assert alertas[1].severidad is Severidad.MEDIA


def test_severidad_en_ingles_de_grafana_prometheus_se_traduce() -> None:
    """Grafana/Prometheus usan severity en ingles (critical/warning/info), no en
    espanol. Antes caian todas en MEDIA por defecto: una alerta `critical` quedaba
    elegible para autoremediarse sola. Ver docs/plan-aiops.md Fase 0.5."""
    obs = Falso(
        {
            "/api/v1/alerts": {
                "data": {
                    "alerts": [
                        {"state": "firing", "labels": {"alertname": "A", "severity": "critical"}},
                        {"state": "firing", "labels": {"alertname": "B", "severity": "warning"}},
                        {"state": "firing", "labels": {"alertname": "C", "severity": "info"}},
                        {"state": "firing", "labels": {"alertname": "D", "severity": "high"}},
                        {"state": "firing", "labels": {"alertname": "E", "severity": "low"}},
                    ]
                }
            }
        }
    )
    severidades = {a.nombre: a.severidad for a in obs.alertas_activas()}
    assert severidades["A"] is Severidad.CRITICA
    assert severidades["B"] is Severidad.MEDIA
    assert severidades["C"] is Severidad.BAJA
    assert severidades["D"] is Severidad.ALTA
    assert severidades["E"] is Severidad.BAJA


def test_severidad_desconocida_es_fail_safe_critica() -> None:
    """Un valor de severity no reconocido no debe quedar elegible para autoremediar:
    se trata como critica (escala en vez de ejecutar), no como media."""
    obs = Falso(
        {
            "/api/v1/alerts": {
                "data": {
                    "alerts": [
                        {"state": "firing", "labels": {"alertname": "Z", "severity": "rara"}},
                        {"state": "firing", "labels": {"alertname": "W"}},
                    ]
                }
            }
        }
    )
    severidades = {a.nombre: a.severidad for a in obs.alertas_activas()}
    assert severidades["Z"] is Severidad.CRITICA
    assert severidades["W"] is Severidad.CRITICA


def test_activeat_desambigua_disparos_repetidos_y_llena_disparada_en() -> None:
    """Dos disparos de la misma alerta+servicio (ServiceDown en checkout, resuelto y
    vuelto a fallar) deben dar ids distintos, o Ciclo.abrir() los trataria como el
    mismo incidente ya cerrado. Tambien debe quedar Alerta.disparada_en para el MTTR
    real (Fase 0.5 del plan)."""
    obs = Falso(
        {
            "/api/v1/alerts": {
                "data": {
                    "alerts": [
                        {
                            "state": "firing",
                            "activeAt": "2026-10-05T10:00:00Z",
                            "labels": {"alertname": "ServiceDown", "service": "checkout"},
                        },
                        {
                            "state": "firing",
                            "activeAt": "2026-10-05T11:30:00Z",
                            "labels": {"alertname": "ServiceDown", "service": "checkout"},
                        },
                    ]
                }
            }
        }
    )
    alertas = obs.alertas_activas()
    assert alertas[0].id != alertas[1].id
    assert alertas[1].disparada_en is not None
    assert alertas[1].disparada_en > alertas[0].disparada_en  # type: ignore[operator]


def test_metrica_y_sin_datos() -> None:
    obs = Falso({"/api/v1/query": {"data": {"result": [{"value": [0, "0"]}]}}})
    assert obs.metrica("checkout", "up") == 0.0
    assert "checkout" in obs.urls[-1]
    assert obs.metrica("checkout", "inexistente") is None
    assert Falso({}).metrica("checkout", "up") is None
    with pytest.raises(AccionNoPermitida):
        obs.metrica('x"}) or vector(1', "up")


def test_metrica_usa_la_etiqueta_de_servicio_configurada() -> None:
    """AIOPS_SERVICE_LABEL debia usarse tambien en las queries de metrica(), no solo
    en alertas_activas()/logs(): antes quedaba fijo en job=. Ver plan Fase 0.5."""
    import urllib.parse

    obs = Falso(
        {"/api/v1/query": {"data": {"result": [{"value": [0, "1"]}]}}},
        etiqueta_servicio="mi_etiqueta",
    )
    obs.metrica("checkout", "up")
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(obs.urls[-1]).query)["query"][0]
    assert 'mi_etiqueta="checkout"' in query
    assert "job=" not in query


def test_logs() -> None:
    obs = Falso(
        {
            "/loki/": {
                "data": {"result": [{"values": [["1", "a"], ["2", "b"]]}, {"values": [["3", "c"]]}]}
            }
        }
    )
    assert obs.logs("checkout", 2) == ["a", "b"]
    assert PrometheusLoki("http://p").logs("checkout", 5) == []
