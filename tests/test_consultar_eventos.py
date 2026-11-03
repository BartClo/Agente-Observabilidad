"""consultar_eventos: evidencia de solo lectura sobre los pods del servicio del incidente.
El servicio lo fija el incidente, la salida se sanea y una falla del cluster no corta el ciclo."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from agents.aiops import agente, runtime, tools
from domain.aiops_core.auditoria import Auditoria
from domain.aiops_core.ciclo import Ciclo, ErrorCiclo
from domain.aiops_core.politicas import Politica
from domain.aiops_core.simulador import EntornoSimulado
from infra.acciones_k8s import BackendKubernetes
from tests.test_infra_acciones_k8s import _Resp

RAIZ = Path(__file__).resolve().parent.parent


class _Investigacion:
    def __init__(self, lineas: list[str] | Exception) -> None:
        self.lineas = lineas
        self.pedidos: list[tuple[str, int]] = []

    def eventos(self, servicio: str, maximo: int) -> list[str]:
        self.pedidos.append((servicio, maximo))
        if isinstance(self.lineas, Exception):
            raise self.lineas
        return self.lineas


def _ciclo(investigacion: Any) -> tuple[Ciclo, str]:
    env = EntornoSimulado()
    alerta = env.inyectar_fallo("api", "pod_fallido")
    ciclo = Ciclo(env, env, Politica(), Auditoria(), investigacion=investigacion)
    return ciclo, ciclo.abrir(alerta.id).id


def test_el_servicio_sale_del_incidente_y_la_salida_se_sanea() -> None:
    inv = _Investigacion(["evento Warning Failed x3: password=hunter2 ImagePullBackOff"])
    ciclo, inc_id = _ciclo(inv)
    salida = ciclo.eventos(inc_id, maximo=999)
    assert inv.pedidos == [("api", 50)]  # servicio del incidente; el tope lo pone el dominio
    assert "hunter2" not in salida[0] and "ImagePullBackOff" in salida[0]
    assert any(e.tipo == "consulta_eventos" for e in ciclo.auditoria.de_incidente(inc_id))


def test_sin_investigacion_o_con_el_cluster_caido_es_error_de_ciclo_no_excepcion() -> None:
    ciclo, inc_id = _ciclo(None)
    with pytest.raises(ErrorCiclo, match="no esta disponible"):
        ciclo.eventos(inc_id)
    ciclo, inc_id = _ciclo(_Investigacion(RuntimeError("API de Kubernetes respondio 403")))
    with pytest.raises(ErrorCiclo, match="403"):
        ciclo.eventos(inc_id)


def test_la_tool_delimita_el_resultado_y_devuelve_el_error_como_texto() -> None:
    ciclo, inc_id = _ciclo(_Investigacion(["pod api-1: fase=Pending"]))
    runtime.reset(ciclo)
    assert tools.consultar_eventos(inc_id) == "<<<\npod api-1: fase=Pending\n>>>"
    assert tools.consultar_eventos("INC-NO-EXISTE").startswith("ERROR")
    runtime.reset()


def test_la_tool_no_acepta_objeto_ni_namespace_elegidos_por_el_llm() -> None:
    import inspect

    assert list(inspect.signature(tools.consultar_eventos).parameters) == ["incidente_id"]


def test_el_simulador_tambien_investiga() -> None:
    env = EntornoSimulado()
    env.inyectar_fallo("api", "pod_fallido")
    assert "listo=no" in env.eventos("api", 5)[0]
    assert "listo=si" in env.eventos("checkout", 5)[0]


def test_runtime_conecta_el_backend_que_sabe_leer_eventos(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIOPS_BACKEND", "simulado")
    runtime.reset()
    ciclo = runtime.armar(persistencia="memoria")
    assert ciclo._investigacion is not None
    runtime.reset()


def test_interruptor_aiops_investigacion_quita_tool_y_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    con = agente._definicion()
    assert "consultar_eventos" in {t.__name__ for t in con["tools"]}
    assert "consultar_eventos" in con["system_prompt"] and "<!--inv" not in con["system_prompt"]
    monkeypatch.setenv("AIOPS_INVESTIGACION", "0")
    sin = agente._definicion()
    assert "consultar_eventos" not in {t.__name__ for t in sin["tools"]}
    assert "consultar_eventos" not in sin["system_prompt"]
    assert "<!--" not in sin["system_prompt"]


# --- adaptador de Kubernetes ----------------------------------------------------------

_POD = {
    "metadata": {"name": "api-7d9"},
    "status": {
        "phase": "Pending",
        "containerStatuses": [
            {
                "name": "api",
                "ready": False,
                "restartCount": 4,
                "state": {
                    "waiting": {"reason": "ImagePullBackOff", "message": "pull access denied"}
                },
                "lastState": {"terminated": {"reason": "Error", "exitCode": 1}},
            }
        ],
    },
}
_EVENTOS = [
    {
        "involvedObject": {"name": "api-7d9"},
        "type": "Warning",
        "reason": "Failed",
        "count": 3,
        "message": "Failed to pull image",
        "lastTimestamp": "2026-11-03T10:00:00Z",
    },
    {
        "involvedObject": {"name": "otro-pod"},
        "reason": "Ruido",
        "lastTimestamp": "2026-11-03T11:00:00Z",
    },
]


@pytest.fixture
def pedidos(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    registro: list[Any] = []

    def falso_urlopen(req: Any, timeout: float, context: Any) -> _Resp:
        registro.append(req)
        if "/events" in req.full_url:
            return _Resp(json.dumps({"items": _EVENTOS}).encode())
        vacio = "app%3Dvacio" in req.full_url
        return _Resp(json.dumps({"items": [] if vacio else [_POD]}).encode())

    monkeypatch.setattr("urllib.request.urlopen", falso_urlopen)
    return registro


def test_k8s_describe_el_estado_y_los_eventos_del_pod_en_solo_lectura(pedidos: list[Any]) -> None:
    lineas = BackendKubernetes("https://k8s:6443", "tok", "aiops-lab").eventos("api")
    assert {r.get_method() for r in pedidos} == {"GET"}
    assert all("/namespaces/aiops-lab/" in r.full_url for r in pedidos)
    assert "labelSelector=app%3Dapi" in pedidos[0].full_url
    texto = "\n".join(lineas)
    assert "fase=Pending" in texto and "reinicios=4" in texto
    assert "ahora waiting ImagePullBackOff" in texto and "antes terminated Error codigo=1" in texto
    assert "evento Warning Failed x3: Failed to pull image" in texto
    assert "Ruido" not in texto  # eventos de pods que no son del servicio


def test_k8s_sin_pods_lo_dice_y_no_consulta_eventos(pedidos: list[Any]) -> None:
    lineas = BackendKubernetes("https://k8s:6443", "tok", "aiops-lab").eventos("vacio")
    assert lineas == ["sin pods app=vacio en aiops-lab"]
    assert len(pedidos) == 1


def test_el_rbac_solo_agrega_lectura_de_eventos() -> None:
    docs = list(yaml.safe_load_all((RAIZ / "k8s-lab" / "rbac-aiops.yaml").read_text("utf-8")))
    reglas = next(d for d in docs if d and d["kind"] == "Role")["rules"]
    eventos = [r for r in reglas if "events" in r["resources"]]
    assert eventos == [{"apiGroups": [""], "resources": ["events"], "verbs": ["list"]}]
    assert not any("secrets" in r["resources"] or "pods/exec" in r["resources"] for r in reglas)
