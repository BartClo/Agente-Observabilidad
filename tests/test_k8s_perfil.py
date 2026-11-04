"""Kubernetes con perfil: destino mapeable y ningun namespace fuera de los permitidos."""

from __future__ import annotations

from typing import Any

import pytest

from infra import perfil as perfiles
from infra.acciones_k8s import BackendKubernetes
from infra.perfil import DestinoK8s


class Falso(BackendKubernetes):
    def __init__(self, **kw: Any) -> None:
        super().__init__("https://k8s", "t", "base", **kw)
        self.rutas: list[str] = []

    def _pedir(self, metodo: str, ruta: str, cuerpo: Any, tipo: str, timeout_s: int) -> Any:
        self.rutas.append(f"{metodo} {ruta}")
        return {"items": [{"metadata": {"name": "p1"}}]}


def _backend() -> Falso:
    return Falso(
        namespaces_permitidos=frozenset({"base", "pagos"}),
        servicios={
            "web": DestinoK8s("pagos", "web-v2", "web-front"),
            "fuera": DestinoK8s("kube-system"),
        },
    )


def test_usa_namespace_deployment_y_selector_del_mapa() -> None:
    b = _backend()
    b.ejecutar("restart_service", "web", 5)
    b.ejecutar("recreate_pod", "web", 5)
    assert b.rutas[0] == "PATCH /apis/apps/v1/namespaces/pagos/deployments/web-v2"
    assert b.rutas[1] == "DELETE /api/v1/namespaces/pagos/pods?labelSelector=app%3Dweb-front"


def test_servicio_sin_mapa_usa_el_namespace_base() -> None:
    b = _backend()
    b.ejecutar("restart_service", "otro", 5)
    assert b.rutas == ["PATCH /apis/apps/v1/namespaces/base/deployments/otro"]


@pytest.mark.parametrize(
    "operar",
    [
        lambda b: b.ejecutar("recreate_pod", "fuera", 5),
        lambda b: b.ejecutar("restart_service", "fuera", 5),
        lambda b: b.eventos("fuera"),
    ],
)
def test_namespace_no_permitido_se_niega_sin_llamar_a_la_api(operar: Any) -> None:
    b = _backend()
    with pytest.raises(RuntimeError, match="no permitido"):
        operar(b)
    assert b.rutas == []


def test_el_perfil_no_acepta_destino_fuera_de_sus_namespaces() -> None:
    datos = {
        "version": 1,
        "aprobado": True,
        "aprobado_por": "ana",
        "entorno": "qa",
        "categorias": [
            {
                "id": "c",
                "alertas": ["A"],
                "runbook": "RB-001",
                "senal": {"metrica": "up", "operador": ">=", "umbral": 1},
            }
        ],
        "kubernetes": {"namespaces": ["a"], "servicios": {"w": {"namespace": "b"}}},
    }
    with pytest.raises(perfiles.PerfilInvalido, match="no permitido"):
        perfiles.parsear(datos)
