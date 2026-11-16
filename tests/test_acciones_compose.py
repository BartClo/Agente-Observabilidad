"""Acciones en Docker Compose sin docker.sock: el agente pide (infra/acciones_compose.py) y
el host decide y ejecuta (deploy/aifactory/ejecutor/aiops_ejecutor.py)."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from domain.aiops_core.acciones import AccionNoPermitida, ejecutar_accion
from infra.acciones_compose import BackendSolicitudes

_RUTA = (
    Path(__file__).resolve().parent.parent
    / "deploy"
    / "aifactory"
    / "ejecutor"
    / "aiops_ejecutor.py"
)
_spec = importlib.util.spec_from_file_location("aiops_ejecutor", _RUTA)
assert _spec and _spec.loader
ejecutor_mod: Any = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ejecutor_mod)


class _Docker:
    def __init__(self, codigo: int = 0) -> None:
        self.comandos: list[list[str]] = []
        self.codigo = codigo

    def __call__(self, cmd: list[str]) -> subprocess.CompletedProcess[str]:
        self.comandos.append(cmd)
        return subprocess.CompletedProcess(cmd, self.codigo, "", "boom" if self.codigo else "")


def _ejecutor(tmp: Path, docker: _Docker, permitidos: str = "frontend\n# nada\nqa-agent\n") -> Any:
    lista = tmp / "permitidos"
    lista.write_text(permitidos, encoding="utf-8")
    return ejecutor_mod.Ejecutor(tmp / "sol", lista, max_por_hora=2, correr=docker)


def _pedido(**cambios: Any) -> dict[str, Any]:
    return {"accion": "restart_service", "servicio": "frontend", "ts": 1000.0, **cambios}


def test_ida_y_vuelta_agente_ejecutor(tmp_path: Path) -> None:
    docker = _Docker()
    e = _ejecutor(tmp_path, docker)
    backend = BackendSolicitudes(tmp_path / "sol", intervalo_s=0.05)
    corriendo = True

    def host() -> None:
        while corriendo:
            if e.pend.exists():
                e.procesar_pendientes()
            time.sleep(0.05)

    hilo = threading.Thread(target=host, daemon=True)
    hilo.start()
    try:
        resumen = ejecutar_accion(backend, "restart_service", "frontend")
    finally:
        corriendo = False
    assert "docker restart ia-factory-frontend: ok" in resumen
    assert docker.comandos == [["docker", "restart", "--time", "30", "ia-factory-frontend"]]
    assert not list((tmp_path / "sol" / "pendientes").glob("*.json"))
    assert not list((tmp_path / "sol" / "resultados").glob("*.json"))


def test_el_rechazo_del_host_llega_como_error(tmp_path: Path) -> None:
    e = _ejecutor(tmp_path, _Docker())
    backend = BackendSolicitudes(tmp_path / "sol", intervalo_s=0.05)
    threading.Timer(0.2, e.procesar_pendientes).start()
    with pytest.raises(RuntimeError, match="lista de servicios permitidos"):
        backend.ejecutar("restart_service", "postgres", timeout_s=10)


def test_sin_ejecutor_vence_y_retira_el_pedido(tmp_path: Path) -> None:
    backend = BackendSolicitudes(tmp_path / "sol", intervalo_s=0.05)
    with pytest.raises(TimeoutError):
        backend.ejecutar("restart_service", "frontend", timeout_s=1)
    assert not list((tmp_path / "sol" / "pendientes").glob("*.json"))  # no se ejecuta tarde


def test_el_agente_no_puede_pedir_acciones_fuera_de_la_lista(tmp_path: Path) -> None:
    with pytest.raises(AccionNoPermitida):
        ejecutar_accion(BackendSolicitudes(tmp_path), "rm_rf", "frontend")
    with pytest.raises(AccionNoPermitida):
        ejecutar_accion(BackendSolicitudes(tmp_path), "restart_service", "x; docker rm -f db")


@pytest.mark.parametrize(
    ("pedido", "motivo"),
    [
        (_pedido(accion="recreate_pod"), "accion no permitida"),
        (_pedido(accion="compress_old_logs"), "accion no permitida"),
        (_pedido(servicio="postgres"), "lista de servicios permitidos"),
        (_pedido(servicio="frontend;rm"), "invalido"),
        (_pedido(servicio="nada"), "lista de servicios permitidos"),  # comentado no cuenta
        (_pedido(ts=1000.0 - 500), "vencida"),
    ],
)
def test_el_host_valida_con_sus_reglas(tmp_path: Path, pedido: dict[str, Any], motivo: str) -> None:
    docker = _Docker()
    ok, detalle = _ejecutor(tmp_path, docker).decidir(pedido, ahora=1000.0)
    assert not ok and motivo in detalle
    assert docker.comandos == []  # nunca llego a Docker


def test_limite_de_reinicios_por_hora(tmp_path: Path) -> None:
    e = _ejecutor(tmp_path, _Docker())
    assert e.decidir(_pedido(ts=1000.0), 1000.0)[0]
    assert e.decidir(_pedido(ts=1010.0), 1010.0)[0]
    ok, detalle = e.decidir(_pedido(ts=1020.0), 1020.0)
    assert not ok and "limite" in detalle
    assert e.decidir(_pedido(ts=1000.0 + 3700), 1000.0 + 3700)[0]  # paso la hora
    assert e.decidir(_pedido(servicio="qa-agent", ts=1020.0), 1020.0)[0]  # otro servicio


def test_falla_de_docker_no_cuenta_para_el_limite(tmp_path: Path) -> None:
    e = _ejecutor(tmp_path, _Docker(codigo=1))
    ok, detalle = e.decidir(_pedido(), 1000.0)
    assert not ok and "boom" in detalle
    assert e._historial["frontend"] == []


def test_solicitud_ilegible_o_con_id_raro_no_ejecuta(tmp_path: Path) -> None:
    docker = _Docker()
    e = _ejecutor(tmp_path, docker)
    e.pend.mkdir(parents=True)
    (e.pend / "basura.json").write_text("no es json", encoding="utf-8")
    (e.pend / "../escape.json".replace("../", "x")).write_text(
        json.dumps(_pedido()), encoding="utf-8"
    )
    assert e.procesar_pendientes(ahora=1000.0) == 0
    assert docker.comandos == [] and not list(e.pend.glob("*.json"))


def test_sin_archivo_de_permitidos_no_se_reinicia_nada(tmp_path: Path) -> None:
    e = ejecutor_mod.Ejecutor(tmp_path / "sol", tmp_path / "no-existe", correr=_Docker())
    assert not e.decidir(_pedido(), 1000.0)[0]


def test_inspeccionar_resume_el_estado_sin_limite_ni_reinicio(tmp_path: Path) -> None:
    salida = json.dumps(
        [
            {
                "RestartCount": 2,
                "State": {
                    "Status": "exited",
                    "ExitCode": 137,
                    "OOMKilled": True,
                    "StartedAt": "a",
                    "FinishedAt": "b",
                    "Health": {"Status": "unhealthy", "FailingStreak": 3, "Log": [{"Output": "x"}]},
                },
            }
        ]
    )

    class _Inspect(_Docker):
        def __call__(self, cmd: list[str]) -> subprocess.CompletedProcess[str]:
            self.comandos.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, salida, "")

    docker = _Inspect()
    e = _ejecutor(tmp_path, docker)
    for _ in range(5):  # lectura: no cuenta para el limite de reinicios
        ok, detalle = e.decidir(_pedido(accion="inspeccionar"), 1000.0)
        assert ok
    assert "codigo_salida=137 oom=True reinicios=2" in detalle
    assert "healthcheck=unhealthy" in detalle
    assert all(c[:2] == ["docker", "inspect"] for c in docker.comandos)
    assert not e.decidir(_pedido(accion="inspeccionar", servicio="postgres"), 1000.0)[0]


def test_el_backend_expone_el_inspect_como_investigacion(tmp_path: Path) -> None:
    from domain.aiops_core.observabilidad import InvestigacionPort

    backend = BackendSolicitudes(tmp_path / "sol", intervalo_s=0.05)
    assert isinstance(backend, InvestigacionPort)
    with pytest.raises(RuntimeError):  # sin ejecutor: error legible, no cuelga
        backend.eventos("frontend", 5)
