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


def test_el_servicio_compose_arranca_sin_acciones_y_en_nivel_1_por_defecto() -> None:
    """Actuar es opt-in desde aiops.env: sin tocarlo, el agente solo observa."""
    entorno = _compose()["x-aiops"]["environment"]
    assert entorno["AIOPS_ACTIONS"] == "${AIOPS_ACTIONS:-ninguna}"
    assert entorno["AIOPS_AUTONOMY_LEVEL"] == "${AIOPS_AUTONOMY_LEVEL:-1}"
    assert entorno["AIOPS_ALLOWED_ENVS"] == "${AIOPS_ALLOWED_ENVS:-dev}"


def test_las_acciones_van_por_solicitud_al_host_sin_socket() -> None:
    aiops = _compose()["x-aiops"]
    assert aiops["environment"]["AIOPS_SOLICITUDES_DIR"] == "/solicitudes"
    assert any(str(v).endswith(":/solicitudes") for v in aiops["volumes"])
    ejecutor = RAIZ / "deploy" / "aifactory" / "ejecutor"
    unidad = (ejecutor / "aiops-ejecutor.service").read_text(encoding="utf-8")
    assert "User=aiops-exec" in unidad and "NoNewPrivileges=true" in unidad
    permitidos = (ejecutor / "servicios-permitidos.example").read_text(encoding="utf-8")
    activos = {s.strip() for s in permitidos.splitlines() if s.strip() and not s.startswith("#")}
    assert not activos & {"postgres", "redis", "prometheus", "alertmanager", "aiops-agent"}


def test_el_perfil_trae_consultas_de_investigacion_del_contenedor() -> None:
    from infra.observabilidad import InvestigacionPrometheus

    perfil = _perfil_aprobado()
    assert set(perfil.investigacion) == {"contenedor_estado", "contenedor_salud", "responde"}

    class _Obs:
        def series(self, plantilla: str, servicio: str) -> list[tuple[dict[str, str], str]]:
            if "state" in plantilla:
                return [({"__name__": "x", "service_name": servicio, "state": "exited"}, "0")]
            return []

    lineas = InvestigacionPrometheus(_Obs(), perfil.investigacion).eventos("qa-agent", 10)  # type: ignore[arg-type]
    assert "contenedor_estado{service_name=qa-agent,state=exited} = 0" in lineas
    assert "responde: sin datos" in lineas


def test_el_prompt_investiga_antes_de_escalar_aunque_no_sea_elegible() -> None:
    prompt = (RAIZ / "agents" / "aiops" / "prompt.md").read_text(encoding="utf-8")
    paso4 = prompt[prompt.index("4. `clasificar_incidente`") : prompt.index("5. ")]
    assert "registrar_diagnostico" in paso4 and "DESPUES `escalar_a_humano`" in paso4
    assert "Sos " not in prompt  # espanol neutro


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
    assert comando.index("perfil.activo()") < comando.index("alembic upgrade head")
    assert comando.index("alembic upgrade head") < comando.index("uvicorn")
    assert servicios["aiops-worker"]["depends_on"]["aiops-agent"]["condition"] == "service_healthy"


def test_los_montajes_y_el_build_apuntan_a_rutas_que_existen() -> None:
    """Compose resuelve las rutas relativas al archivo, no al directorio desde donde se corre."""
    base = COMPOSE.parent
    build = _compose()["x-aiops"]["build"]
    assert (base / build["context"] / build["dockerfile"]).is_file()
    for volumen in _compose()["x-aiops"]["volumes"]:
        origen = volumen.split(":")[0]
        if origen.startswith("${"):
            continue  # directorio del host (solicitudes), no del repositorio
        assert (base / origen / PERFIL.name).is_file(), volumen


def test_el_archivo_de_secretos_no_entra_ni_a_git_ni_a_la_imagen() -> None:
    for ignorar in (".gitignore", ".dockerignore"):
        assert "deploy/aifactory/aiops.env" in (RAIZ / ignorar).read_text(encoding="utf-8")


def test_la_verificacion_espera_a_que_prometheus_vea_el_servicio() -> None:
    entorno = _compose()["x-aiops"]["environment"]
    assert entorno["AIOPS_VERIFY_WINDOW_S"] == "${AIOPS_VERIFY_WINDOW_S:-90}"
    assert entorno["AIOPS_VERIFY_INTERVAL_S"] == "${AIOPS_VERIFY_INTERVAL_S:-10}"
