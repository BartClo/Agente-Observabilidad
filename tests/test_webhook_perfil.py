"""Webhook con perfil: los campos salen del mapeo y el entorno nunca del payload."""

from __future__ import annotations

from typing import Any

import pytest

from domain.aiops_core.modelos import Severidad
from infra import perfil as perfiles
from infra.alertas_webhook import alerta_desde_grafana, alertas_con_perfil

BASE: dict[str, Any] = {
    "version": 1,
    "aprobado": True,
    "aprobado_por": "ana",
    "entorno": "qa",
    "observabilidad": {"etiqueta_servicio": "app"},
    "categorias": [
        {
            "id": "c",
            "alertas": ["A"],
            "runbook": "RB-001",
            "senal": {"metrica": "up", "operador": ">=", "umbral": 1},
        }
    ],
}


def test_formato_grafana_por_defecto_coincide_con_el_parser_de_siempre() -> None:
    item = {
        "status": "firing",
        "labels": {"alertname": "A", "app": "web", "severity": "warning", "env": "prod"},
        "annotations": {"summary": "s"},
        "startsAt": "2026-01-01T00:00:00Z",
        "fingerprint": "f1",
    }
    [(alerta, firing)] = alertas_con_perfil({"alerts": [item]}, perfiles.parsear(BASE))
    esperado, _ = alerta_desde_grafana(item, "app")
    assert firing is True
    assert alerta.id == esperado.id and alerta.severidad == esperado.severidad
    assert alerta.disparada_en == esperado.disparada_en
    assert alerta.entorno == "qa"  # el payload decia prod


def test_mapeo_propio_y_una_sola_alerta_por_payload() -> None:
    perfil = perfiles.parsear(
        {
            **BASE,
            "webhook": {
                "lista": "",
                "nombre": "regla",
                "servicio": "objetivo.nombre",
                "severidad": "prioridad",
                "resumen": "texto",
                "inicio": "cuando",
                "huella": "uid",
                "estado": "fase",
                "valor_firing": "abierta",
                "severidades": {"P3": "media"},
            },
        }
    )
    payload = {
        "regla": "A",
        "objetivo": {"nombre": "web"},
        "prioridad": "p3",
        "texto": "caida",
        "uid": "u1",
        "fase": "cerrada",
    }
    [(alerta, firing)] = alertas_con_perfil(payload, perfil)
    assert (alerta.id, alerta.servicio, alerta.resumen) == ("A:web:u1", "web", "caida")
    assert alerta.severidad is Severidad.MEDIA
    assert firing is False


def test_severidad_desconocida_es_critica_y_no_autonoma() -> None:
    item = {"labels": {"alertname": "A", "app": "w", "severity": "P9"}}
    [(alerta, _)] = alertas_con_perfil({"alerts": [item]}, perfiles.parsear(BASE))
    assert alerta.severidad is Severidad.CRITICA


@pytest.mark.parametrize("payload", [{"alerts": "x"}, {"alerts": ["x"]}])
def test_payload_malformado_es_error(payload: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        alertas_con_perfil(payload, perfiles.parsear(BASE))


def test_mapeo_con_clave_desconocida_no_carga() -> None:
    with pytest.raises(perfiles.PerfilInvalido):
        perfiles.parsear({**BASE, "webhook": {"nomber": "x"}})
