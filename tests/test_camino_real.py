"""Camino real (Grafana -> webhook -> cola -> worker): el runner espera al worker en vez de
invocar el ciclo. Sin red ni Docker: las llamadas se simulan."""

from __future__ import annotations

import subprocess
import time
import urllib.request
from typing import Any

import pytest

from scripts import experimento

ESC = experimento.ESCENARIOS["pod_fallido"]


def _inc(id_: str, alerta: str, servicio: str, abierto_en: float) -> dict[str, object]:
    return {"id": id_, "alerta": alerta, "servicio": servicio, "abierto_en": abierto_en}


@pytest.fixture(autouse=True)
def _sin_esperas(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(time, "sleep", lambda s: None)


def test_buscar_incidente_nuevo_toma_el_primero_de_esta_alerta_despues_de_desde() -> None:
    lista = [
        _inc("INC-viejo", "PodFailed", "api", 100.0),
        _inc("INC-otro", "ServiceDown", "checkout", 205.0),
        _inc("INC-b", "PodFailed", "api", 212.0),
        _inc("INC-a", "PodFailed", "api", 210.0),
    ]
    encontrado = experimento.buscar_incidente_nuevo(lista, ESC, 200.0)
    assert encontrado is not None and encontrado["id"] == "INC-a"
    assert experimento.buscar_incidente_nuevo(lista, ESC, 300.0) is None


def test_espera_hasta_que_el_worker_abre_y_cierra_el_incidente(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    listas = iter([[], [], [_inc("INC-1", "PodFailed", "api", 210.0)]])
    estados = ["abierto", "accion_ejecutada", "resuelto"]
    lecturas = {"n": 0}

    def incidente(_: str) -> dict[str, object]:
        n = lecturas["n"]
        lecturas["n"] += 1
        return {"estado": estados[min(n, 2)], "modelo_llm": "deepseek:deepseek-chat"}

    monkeypatch.setattr(experimento, "_listar_incidentes", lambda: next(listas))
    monkeypatch.setattr(experimento, "_incidente", incidente)
    assert experimento.esperar_camino_real(ESC, 200.0) == ("INC-1", "")


def test_espera_a_que_el_worker_registre_el_costo_antes_de_leer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regresion: un incidente escalado tras 7 turnos aparecia con turnos=0 y tokens=0 porque
    el runner lo leia antes de que el worker registrara el costo."""
    monkeypatch.setattr(
        experimento, "_listar_incidentes", lambda: [_inc("INC-1", "PodFailed", "api", 210.0)]
    )
    lecturas = {"n": 0}

    def incidente(_: str) -> dict[str, object]:
        lecturas["n"] += 1
        # terminal desde la primera lectura; el costo aparece recien en la tercera
        return {"estado": "escalado", "modelo_llm": "m" if lecturas["n"] >= 3 else None}

    monkeypatch.setattr(experimento, "_incidente", incidente)
    assert experimento.esperar_camino_real(ESC, 200.0) == ("INC-1", "")
    assert lecturas["n"] >= 3
    lecturas["n"] = -100  # nunca aparece: con espera 0 no se queda esperando
    assert experimento.esperar_camino_real(ESC, 200.0, espera_costo_s=0.0) == ("INC-1", "")


def test_si_nadie_abre_el_incidente_es_un_error_de_infraestructura(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(experimento, "_listar_incidentes", lambda: [])
    incidente, motivo = experimento.esperar_camino_real(ESC, 200.0, espera_apertura_s=0.0)
    assert incidente is None and motivo.startswith("infra:")


def test_si_no_termina_es_un_error_del_agente_y_no_se_excluye(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        experimento, "_listar_incidentes", lambda: [_inc("INC-1", "PodFailed", "api", 210.0)]
    )
    monkeypatch.setattr(experimento, "_incidente", lambda i: {"estado": "abierto"})
    incidente, motivo = experimento.esperar_camino_real(ESC, 200.0, espera_cierre_s=0.0)
    assert incidente == "INC-1" and motivo.startswith("agente:")


def _sh_falso(llamadas: list[list[str]], falla_run: bool = False) -> Any:
    def falso(args: list[str], timeout: float = 300, reintentos: int = 1) -> Any:
        llamadas.append(list(args))
        rc = 1 if falla_run and args[:3] == ["docker", "compose", "run"] else 0
        return subprocess.CompletedProcess(args, rc, "", "boom" if rc else "")

    return falso


def test_el_worker_de_laboratorio_lleva_el_nivel_y_se_restaura(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llamadas: list[list[str]] = []
    monkeypatch.setattr(experimento, "_sh", _sh_falso(llamadas))
    with experimento.worker_de_laboratorio(1, "6443"):
        levantado = llamadas[-1]
        assert levantado[:6] == ["docker", "compose", "run", "-d", "--name", "aiops-worker-lab"]
        assert "AIOPS_AUTONOMY_LEVEL=1" in levantado and levantado[-1] == "worker"
    assert llamadas[0] == ["docker", "compose", "stop", "worker"]
    assert ["docker", "rm", "-f", "aiops-worker-lab"] in llamadas
    assert llamadas[-1] == ["docker", "compose", "start", "worker"]


def test_si_no_levanta_el_worker_de_laboratorio_deja_el_normal_andando(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llamadas: list[list[str]] = []
    monkeypatch.setattr(experimento, "_sh", _sh_falso(llamadas, falla_run=True))
    with pytest.raises(SystemExit, match="worker del laboratorio"):
        with experimento.worker_de_laboratorio(3, "6443"):
            pass
    assert llamadas[-1] == ["docker", "compose", "start", "worker"]


def _preparar_correr(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Simula el laboratorio sano; devuelve la lista de comandos que el runner ejecuto."""
    llamadas: list[list[str]] = []

    def sh(args: list[str], timeout: float = 300, reintentos: int = 1) -> Any:
        llamadas.append(list(args))
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(experimento, "_k8s_sano", lambda: True)
    monkeypatch.setattr(experimento, "_prom", lambda q: False)  # parte de sano
    monkeypatch.setattr(experimento, "_sh", sh)
    monkeypatch.setattr(experimento, "_esperar", lambda *a, **k: True)
    monkeypatch.setattr(experimento, "esperar_alerta_inactiva", lambda alertname: True)
    monkeypatch.setattr(time, "time", lambda: 1000.0)
    monkeypatch.setattr(experimento, "esperar_estable", lambda sana: True)

    class VerificadorFalso:
        def __init__(self, sana: str) -> None:
            pass

        def start(self) -> None:
            pass

        def esperar(self, limite: float) -> float:
            return 1040.0

    monkeypatch.setattr(experimento, "VerificadorExterno", VerificadorFalso)
    return llamadas


def test_correr_por_webhook_registra_via_deteccion_y_mttr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _preparar_correr(monkeypatch)
    monkeypatch.setattr(experimento, "esperar_camino_real", lambda esc, disparo: ("INC-1", ""))
    monkeypatch.setattr(
        experimento,
        "_incidente",
        lambda i: {
            "id": "INC-1",
            "estado": "resuelto",
            "categoria": "pod_fallido",
            "elegible": True,
            "resuelto_autonomo": True,
            "verificado": True,
            "acciones": [{"nombre": "recreate_pod", "ok": True}],
            "abierto_en": 1012.5,
            "cerrado_en": 1040.0,
            "tokens_entrada": 100,
            "tokens_salida": 10,
            "turnos_llm": 5,
            "llamadas_tools": 6,
            "modelo_llm": "deepseek:deepseek-chat",
        },
    )
    fila = experimento.correr("pod_fallido", 1, "llm", 3, "6443", "ajuste", "webhook")
    assert fila["via"] == "webhook" and fila["deteccion_s"] == "12.5"
    assert fila["inicio_atencion"] == "1012.500" and fila["mttr_s"] == "40.0"
    assert fila["error"] == "" and fila["acciones_nombres"] == "recreate_pod:ok"


def test_correr_por_webhook_sin_incidente_queda_como_error_de_infraestructura(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _preparar_correr(monkeypatch)
    monkeypatch.setattr(
        experimento, "esperar_camino_real", lambda esc, disparo: (None, "infra: nadie abrio")
    )
    fila = experimento.correr("pod_fallido", 1, "llm", 3, "6443", "ajuste", "webhook")
    assert str(fila["error"]).startswith("infra:") and fila["incidente"] == ""
    assert fila["via"] == "webhook"


def test_correr_por_webhook_espera_a_que_grafana_vea_la_alerta_en_normal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llamadas = _preparar_correr(monkeypatch)
    monkeypatch.setattr(experimento, "esperar_alerta_inactiva", lambda alertname: False)
    fila = experimento.correr("pod_fallido", 1, "llm", 3, "6443", "ajuste", "webhook")
    assert str(fila["error"]).startswith("infra:") and "Normal" in str(fila["error"])
    assert not any("pod_fallido.sh" in " ".join(c) for c in llamadas)  # no llego a inyectar


def test_correr_recupera_el_servicio_si_nadie_abrio_el_incidente(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llamadas = _preparar_correr(monkeypatch)
    monkeypatch.setattr(
        experimento, "esperar_camino_real", lambda esc, disparo: (None, "infra: nadie abrio")
    )
    fila = experimento.correr("pod_fallido", 1, "llm", 3, "6443", "ajuste", "webhook")
    assert str(fila["error"]).startswith("infra:")
    assert any("pod_fallido.sh" in " ".join(c) for c in llamadas)  # inyecto...
    assert llamadas[-1] == ["sh", "scripts/fallas/recuperar_pod.sh"]  # ...y limpio


def test_alerta_en_alerting_lee_el_estado_de_la_regla(monkeypatch: pytest.MonkeyPatch) -> None:
    import io
    import json

    def reglas(estado: str) -> Any:
        cuerpo = {"data": {"groups": [{"rules": [{"name": "PodFailed", "state": estado}]}]}}
        return lambda url, timeout=10: io.BytesIO(json.dumps(cuerpo).encode())

    monkeypatch.setattr(urllib.request, "urlopen", reglas("firing"))
    assert experimento._alerta_en_alerting("PodFailed") is True  # noqa: SLF001
    monkeypatch.setattr(urllib.request, "urlopen", reglas("pending"))
    assert experimento._alerta_en_alerting("PodFailed") is True  # noqa: SLF001
    monkeypatch.setattr(urllib.request, "urlopen", reglas("inactive"))
    assert experimento._alerta_en_alerting("PodFailed") is False  # noqa: SLF001
    assert experimento._alerta_en_alerting("OtraRegla") is None  # noqa: SLF001

    def cae(url: str, timeout: float = 10) -> Any:
        raise OSError("sin red")

    monkeypatch.setattr(urllib.request, "urlopen", cae)
    assert experimento._alerta_en_alerting("PodFailed") is None  # noqa: SLF001


def test_esperar_alerta_inactiva_espera_la_transicion_a_normal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    estados = iter([True, True, False])
    monkeypatch.setattr(experimento, "_alerta_en_alerting", lambda a: next(estados))
    assert experimento.esperar_alerta_inactiva("PodFailed")
    monkeypatch.setattr(experimento, "_alerta_en_alerting", lambda a: True)
    assert not experimento.esperar_alerta_inactiva("PodFailed", timeout_s=0.0)


def test_t5_exige_lecturas_sanas_seguidas_y_toma_la_primera() -> None:
    v = experimento.VerificadorExterno("x")
    v.registrar(True, 10.0)
    assert v.t5 is None  # un parpadeo no es una recuperacion
    v.registrar(False, 13.0)
    v.registrar(True, 16.0)
    v.registrar(None, 19.0)  # Prometheus no respondio: no corta la racha
    v.registrar(True, 22.0)
    assert v.t5 == 16.0


def test_la_senal_sana_no_es_la_ausencia_de_anomalia() -> None:
    for esc in {**experimento.ESCENARIOS, **experimento.VARIANTES}.values():
        assert esc.sana and esc.sana != esc.anomalia
        assert ">=" in esc.sana or "<=" in esc.sana


def test_estabilidad_reinicia_si_el_servicio_se_cae(monkeypatch: pytest.MonkeyPatch) -> None:
    ahora = {"t": 0.0}
    monkeypatch.setattr(time, "time", lambda: ahora["t"])
    monkeypatch.setattr(time, "sleep", lambda s: ahora.update(t=ahora["t"] + s))
    monkeypatch.setattr(experimento, "_prom", lambda q: not 30 <= ahora["t"] < 40)
    assert experimento.esperar_estable("x", ventana_s=60, limite_s=300)
    assert ahora["t"] >= 90  # la caida a los 30 s reinicio la cuenta


def test_marcas_de_tiempo_del_camino_real(monkeypatch: pytest.MonkeyPatch) -> None:
    v = experimento.VerificadorExterno("x")
    v.t5 = 190.0
    d = {
        "estado": "resuelto",
        "disparada_en": 100.0,
        "abierto_en": 120.0,
        "cerrado_en": 200.0,
        "acciones": [{"ts": 150.0}],
        "linea_de_tiempo": [],
    }
    m = experimento.marcas_de_tiempo(d, 90.0, "webhook", v)
    assert (m["t2"], m["t3"], m["t4"], m["t5"]) == ("100.000", "120.000", "150.000", "190.000")
    assert m["mttr_s"] == "90.0" and m["cierre_interno_s"] == "100.0"


def test_escalado_sin_recuperacion_no_tiene_mttr_y_registra_el_escalamiento(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    v = experimento.VerificadorExterno("x")
    monkeypatch.setattr(v, "esperar", lambda limite: None)
    d = {
        "estado": "escalado",
        "disparada_en": 100.0,
        "linea_de_tiempo": [{"tipo": "escalado", "ts": 130.0, "datos": {}}],
    }
    m = experimento.marcas_de_tiempo(d, 90.0, "webhook", v)
    assert m["mttr_s"] == "" and m["t5"] == "" and m["escalado_en"] == "130.000"


def test_plan_sorteado_intercalado_y_reproducible() -> None:
    cats, vars_ = ["a", "b", "c"], ["a/x", "b/y"]
    plan = experimento.plan_corridas(cats, vars_, 5, 42)
    assert plan == experimento.plan_corridas(cats, vars_, 5, 42)
    assert plan != experimento.plan_corridas(cats, vars_, 5, 43)
    assert sum(c == "a" for _, c in plan) == 5 and sum(c == "a/x" for _, c in plan) == 3
    for n in range(1, 6):  # cada bloque tiene cada escenario una vez
        bloque = [c for m, c in plan if m == n]
        assert len(bloque) == len(set(bloque))
    assert len(experimento.plan_corridas([], vars_, 1, 1)) == 6  # solo variantes


def test_no_inyecta_fuera_de_un_namespace_declarado_y_etiquetado() -> None:
    experimento.validar_namespace("pruebas", "aiops-lab, pruebas", "true")
    with pytest.raises(SystemExit, match="no declarado"):
        experimento.validar_namespace("produccion", "pruebas", "true")
    with pytest.raises(SystemExit, match="etiqueta"):
        experimento.validar_namespace("pruebas", "pruebas", "")


def test_entorno_del_worker_trae_namespace_y_atendedor() -> None:
    env = experimento.entorno_ciclo(3, "https://k8s", "reglas")
    assert env["AIOPS_ATENDEDOR"] == "reglas" and env["AIOPS_K8S_API"] == "https://k8s"
    assert env["AIOPS_K8S_NAMESPACE"] == experimento.NAMESPACE
    assert env["AIOPS_BREAKER_MAX"] == "0"  # el aislamiento tambien para un worker externo
