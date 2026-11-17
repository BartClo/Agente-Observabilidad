"""Laboratorio Docker: los escenarios del experimento caen en el catalogo del perfil y el
ciclo corre con el ejecutor del host, no con Kubernetes."""

from __future__ import annotations

from infra.perfil import cargar
from scripts import experimento as ex


def test_escenarios_docker_estan_en_el_perfil() -> None:
    perfil = cargar("perfiles/docker-lab.yaml")
    alertas = {a: c.id for c in perfil.categorias for a in c.alertas}
    assert ex.DOCKER == ["contenedor_detenido", "contenedor_unhealthy", "servicio_sin_respuesta"]
    for nombre in ex.DOCKER:
        esc = ex.ESCENARIOS[nombre]
        assert alertas[esc.alertname] == esc.categoria  # la falla cae en su categoria
        assert esc.servicio in (perfil.servicios or ())
        assert all(c.remediable for c in perfil.categorias)


def test_entorno_docker_usa_el_ejecutor_y_no_kubernetes() -> None:
    env = " ".join(ex._env_ciclo(3, "", "docker"))
    assert "AIOPS_ACTIONS=compose" in env and "AIOPS_PERFIL=perfiles/docker-lab.yaml" in env
    assert "AIOPS_K8S" not in env
    assert "AIOPS_BREAKER_MAX=0" in env  # mismo aislamiento que el experimento k8s
    assert "AIOPS_ACTIONS=k8s" in " ".join(ex._env_ciclo(3, "1"))


def test_experimento_docker_apaga_el_limite_del_host() -> None:
    assert int(ex.EJECUTOR_MAX_POR_HORA) >= 25  # 5 repeticiones no pueden chocar con el limite
