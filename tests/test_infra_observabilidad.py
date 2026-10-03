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


def test_metrica_y_sin_datos() -> None:
    obs = Falso({"/api/v1/query": {"data": {"result": [{"value": [0, "0"]}]}}})
    assert obs.metrica("checkout", "up") == 0.0
    assert "checkout" in obs.urls[-1]
    assert obs.metrica("checkout", "inexistente") is None
    assert Falso({}).metrica("checkout", "up") is None
    with pytest.raises(AccionNoPermitida):
        obs.metrica('x"}) or vector(1', "up")


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
