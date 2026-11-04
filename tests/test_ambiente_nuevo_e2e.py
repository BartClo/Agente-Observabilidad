"""Sustituto del segundo ambiente real: otro Prometheus (falso), con alertas, metricas, etiquetas y
namespace que el codigo no conoce, conectado SOLO con un perfil. Del webhook al cierre verificado.
No prueba un ambiente real: las respuestas HTTP son falsas."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from agents.aiops import runtime
from domain.aiops_core.catalogo import restaurar_catalogo
from domain.aiops_core.modelos import Estado
from infra import perfil as perfiles
from infra.acciones_k8s import BackendKubernetes
from infra.alertas_webhook import alertas_con_perfil
from infra.observabilidad import PrometheusLoki

PERFIL = """
version: 1
aprobado: true
aprobado_por: ana@equipo
entorno: pre-prod
observabilidad: {etiqueta_servicio: aplicacion, etiqueta_logs: container}
consultas:
  sonda_http: 'min(blackbox_ok{aplicacion="$servicio"})'
webhook:
  severidades: {sev3: media}
categorias:
  - id: web_caida
    alertas: [TiendaSinRespuesta]
    runbook: RB-001
    senal: {metrica: sonda_http, operador: ">=", umbral: 1}
    accion: restart_service
    nivel: 3
kubernetes:
  namespaces: [tienda]
  servicios:
    tienda-web: {namespace: tienda, deployment: tienda-web-v7}
"""


@pytest.fixture
def ambiente(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Any]]:
    ruta = tmp_path / "preprod.yaml"
    ruta.write_text(PERFIL, encoding="utf-8")
    token = tmp_path / "token"
    token.write_text("t", encoding="utf-8")
    for clave, valor in {
        "AIOPS_PERFIL": str(ruta),
        "AIOPS_BACKEND": "prometheus",
        "AIOPS_PROMETHEUS_URL": "http://otro-prom",
        "AIOPS_LOKI_URL": "http://otro-loki",
        "AIOPS_ACTIONS": "k8s",
        "AIOPS_K8S_API": "https://otro-k8s",
        "AIOPS_K8S_TOKEN_FILE": str(token),
        "AIOPS_K8S_NAMESPACE": "tienda",
        "AIOPS_AUTONOMY_LEVEL": "3",
        "AIOPS_ALLOWED_ENVS": "pre-prod",
        "AIOPS_PERSISTENCIA": "memoria",
    }.items():
        monkeypatch.setenv(clave, valor)
    estado: dict[str, Any] = {"sonda": "0", "consultas": [], "logs": [], "k8s": []}

    def prom_falso(self: PrometheusLoki, url: str) -> Any:
        if "otro-loki" in url:
            estado["logs"].append(url)
            return {"data": {"result": [{"values": [["1", "conexion rechazada"]]}]}}
        estado["consultas"].append(url)
        return {"data": {"result": [{"value": [0, estado["sonda"]]}]}}

    def k8s_falso(self: BackendKubernetes, metodo: str, r: str, c: Any, t: str, s: int) -> Any:
        estado["k8s"].append(f"{metodo} {r}")
        estado["sonda"] = "1"  # el reinicio la recupera
        return {}

    monkeypatch.setattr(PrometheusLoki, "_get", prom_falso)
    monkeypatch.setattr(BackendKubernetes, "_pedir", k8s_falso)
    yield estado
    perfiles._cargar_y_activar.cache_clear()
    restaurar_catalogo()


def test_ambiente_desconocido_se_resuelve_solo_con_el_perfil(ambiente: dict[str, Any]) -> None:
    ciclo = runtime.armar()
    payload = {
        "alerts": [
            {
                "status": "firing",
                "labels": {
                    "alertname": "TiendaSinRespuesta",
                    "aplicacion": "tienda-web",
                    "severity": "sev3",
                    "env": "prod",
                },
                "annotations": {"summary": "no responde"},
                "startsAt": "2026-11-04T10:00:00Z",
                "fingerprint": "abc",
            }
        ]
    }
    perfil = perfiles.activo()
    assert perfil is not None
    [(alerta, firing)] = alertas_con_perfil(payload, perfil)
    assert firing and alerta.entorno == "pre-prod"  # no el "prod" del payload

    inc = ciclo.abrir_desde_alerta(alerta).id
    confirmada, _ = ciclo.confirmar_anomalia(inc)
    assert confirmada and "blackbox_ok" in ambiente["consultas"][0]
    categoria, elegible, _ = ciclo.clasificar(inc)
    assert categoria is not None and categoria.id == "web_caida" and elegible
    assert ciclo.logs(inc, 5) == ["conexion rechazada"]
    assert "container" in ambiente["logs"][0]
    ciclo.registrar_diagnostico(inc, "proceso caido", 0.9, "RB-001")
    assert ciclo.ejecutar_remediacion(inc, aprobada=False).ejecutada
    assert ambiente["k8s"] == ["PATCH /apis/apps/v1/namespaces/tienda/deployments/tienda-web-v7"]
    recuperado, _ = ciclo.verificar(inc)
    assert recuperado
    final = ciclo.cerrar(inc)
    assert final.estado is Estado.RESUELTO and final.resuelto_autonomo


def test_el_nombre_viejo_ya_no_es_del_catalogo(ambiente: dict[str, Any]) -> None:
    runtime.armar()
    from domain.aiops_core.catalogo import categoria_para_alerta

    assert categoria_para_alerta("ServiceDown") is None
