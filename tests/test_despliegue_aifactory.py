"""El perfil y el servicio Compose de AI FACTORY: arrancan en observacion y sin privilegios."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

from domain.aiops_core.catalogo import categoria_para_alerta, restaurar_catalogo
from domain.aiops_core.modelos import NivelAutonomia
from infra import perfil as perfiles

RAIZ = Path(__file__).resolve().parent.parent
PERFIL = RAIZ / "perfiles" / "aifactory-dev.yaml"
COMPOSE = RAIZ / "deploy" / "aifactory" / "aiops.yml"


@pytest.fixture(autouse=True)
def _catalogo() -> Iterator[None]:
    yield
    restaurar_catalogo()


def _perfil_aprobado() -> perfiles.Perfil:
    datos = yaml.safe_load(PERFIL.read_text(encoding="utf-8"))
    return perfiles.parsear({**datos, "aprobado": True, "aprobado_por": "revisor"})


def _compose() -> dict[str, Any]:
    datos: dict[str, Any] = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    return datos


def test_el_perfil_versionado_es_un_borrador_y_no_arranca_sin_aprobar() -> None:
    with pytest.raises(perfiles.PerfilInvalido, match="sin aprobar"):
        perfiles.cargar(PERFIL)


def test_el_perfil_aprobado_es_valido_y_todas_las_categorias_solo_observan() -> None:
    perfil = _perfil_aprobado()
    assert perfil.entorno == "dev"
    assert set(perfil.niveles.values()) == {NivelAutonomia.RECOMIENDA}
    assert not perfil.kubernetes.namespaces  # Compose: ninguna accion por Kubernetes


@pytest.mark.parametrize(
    ("alerta", "categoria"),
    [
        ("ServiceDown", "servicio_caido"),
        ("AgentServiceDown", "servicio_caido"),
        ("SyntheticProbeFailed", "servicio_caido"),
        ("ContainerUnhealthy", "contenedor_fallido"),
        ("ContainerStopped", "contenedor_fallido"),
    ],
)
def test_las_alertas_de_reinicio_caen_en_su_categoria(alerta: str, categoria: str) -> None:
    from domain.aiops_core.catalogo import activar_catalogo

    activar_catalogo(_perfil_aprobado().categorias)
    encontrada = categoria_para_alerta(alerta)
    assert encontrada is not None and encontrada.id == categoria


@pytest.mark.parametrize("alerta", ["HostCPUCritical", "LLMProviderUnhealthy", "Watchdog"])
def test_lo_que_no_se_arregla_reiniciando_queda_fuera_del_catalogo(alerta: str) -> None:
    from domain.aiops_core.catalogo import activar_catalogo

    activar_catalogo(_perfil_aprobado().categorias)
    assert categoria_para_alerta(alerta) is None


def test_el_servicio_compose_arranca_sin_acciones_y_en_nivel_1() -> None:
    entorno = _compose()["x-aiops"]["environment"]
    assert entorno["AIOPS_ACTIONS"] == "ninguna"
    assert entorno["AIOPS_AUTONOMY_LEVEL"] == "1"
    assert entorno["AIOPS_ALLOWED_ENVS"] == "dev"


def test_ningun_servicio_monta_el_socket_ni_corre_privilegiado() -> None:
    compose = _compose()
    for nombre, s in {**compose["services"], "x-aiops": compose["x-aiops"]}.items():
        assert not any("docker.sock" in str(v) for v in s.get("volumes", [])), nombre
        assert not s.get("privileged"), nombre


def test_cada_servicio_tiene_limite_de_memoria_y_puertos_solo_en_loopback() -> None:
    servicios = _compose()["services"]
    for nombre, s in servicios.items():
        assert s.get("mem_limit"), nombre
        assert s["container_name"].startswith("ia-factory-"), nombre
        for puerto in s.get("ports", []):
            assert puerto.startswith("127.0.0.1:"), nombre


def test_el_worker_corre_con_scheduler_como_en_el_compose_local() -> None:
    comando = " ".join(_compose()["services"]["aiops-worker"]["command"])
    assert "--with-scheduler" in comando


# Etiquetas reales de cada regla de AI FACTORY (informe de solo lectura del 2026-11-13).
@pytest.mark.parametrize(
    ("labels", "servicio"),
    [
        ({"alertname": "ServiceDown", "job": "rest-api", "instance": "rest-api:8000"}, "rest-api"),
        (
            {"alertname": "ServiceDown", "job": "blackbox-health", "service": "llm-gateway"},
            "llm-gateway",
        ),
        (
            {
                "alertname": "ContainerUnhealthy",
                "job": "docker-healthcheck-exporter",
                "service_name": "redis",
                "container_name": "ia-factory-redis",
            },
            "redis",
        ),
        (
            {"alertname": "SyntheticProbeFailed", "job": "blackbox-health", "service": "maya"},
            "maya",
        ),
    ],
)
def test_el_servicio_sale_de_la_etiqueta_que_trae_cada_regla(
    labels: dict[str, str], servicio: str
) -> None:
    from infra.alertas_webhook import alertas_con_perfil

    payload = {"alerts": [{"status": "firing", "labels": {**labels, "severity": "critical"}}]}
    [(alerta, firing)] = alertas_con_perfil(payload, _perfil_aprobado())
    assert alerta.servicio == servicio and firing


def test_las_consultas_filtran_por_la_etiqueta_real_de_cada_metrica() -> None:
    consultas = _perfil_aprobado().consultas
    assert 'service_name="{s}"' in consultas["contenedor_sano"]
    assert 'job="{s}"' in consultas["servicio_responde"]
    assert 'service="{s}"' in consultas["servicio_responde"]


def test_la_cola_del_agente_usa_un_redis_propio_que_no_expulsa_claves() -> None:
    compose = _compose()
    assert "aiops-redis" in compose["x-aiops"]["environment"]["REDIS_URL"]
    assert "noeviction" in compose["services"]["aiops-redis"]["command"]


def test_la_api_migra_la_base_antes_de_servir_y_el_worker_la_espera() -> None:
    servicios = _compose()["services"]
    comando = " ".join(servicios["aiops-agent"]["command"])
    assert comando.index("alembic upgrade head") < comando.index("uvicorn")
    assert servicios["aiops-worker"]["depends_on"]["aiops-agent"]["condition"] == "service_healthy"
