"""Autonomia por categoria, alerta desconocida sin poder actuar y retomar tras aprobar.
Todo con dobles: sin LLM, Postgres ni Redis. Nada de esto se probo en vivo."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

from agents.aiops import agente, runtime, tools, worker_jobs
from domain.aiops_core.auditoria import Auditoria
from domain.aiops_core.catalogo import restaurar_catalogo
from domain.aiops_core.ciclo import Ciclo, ErrorCiclo
from domain.aiops_core.modelos import Alerta, Estado, NivelAutonomia, Severidad
from domain.aiops_core.politicas import Politica, Veredicto
from infra import perfil as perfiles

PERFIL: dict[str, Any] = {
    "version": 1,
    "aprobado": True,
    "aprobado_por": "ana",
    "entorno": "qa",
    "categorias": [
        {
            "id": "observada",
            "alertas": ["Observada"],
            "runbook": "RB-001",
            "senal": {"metrica": "up", "operador": ">=", "umbral": 1},
            "accion": "restart_service",
        },
        {
            "id": "aprobada",
            "alertas": ["Aprobada"],
            "runbook": "RB-001",
            "senal": {"metrica": "up", "operador": ">=", "umbral": 1},
            "accion": "restart_service",
            "nivel": 2,
        },
        {
            "id": "autonoma",
            "alertas": ["Autonoma"],
            "runbook": "RB-001",
            "senal": {"metrica": "up", "operador": ">=", "umbral": 1},
            "accion": "restart_service",
            "nivel": 4,
        },
    ],
}


class Entorno:
    def __init__(self) -> None:
        self.acciones: list[str] = []

    def alertas_activas(self) -> list[Alerta]:
        return []

    def metrica(self, servicio: str, nombre: str) -> float | None:
        return 0.0

    def logs(self, servicio: str, lineas: int, desde: float | None = None) -> list[str]:
        return ["linea"]

    def ejecutar(self, accion: str, servicio: str, timeout_s: int) -> str:
        self.acciones.append(accion)
        return "ok"


@pytest.fixture
def perfil_activo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    ruta = tmp_path / "p.yaml"
    ruta.write_text(yaml.safe_dump(PERFIL), encoding="utf-8")
    monkeypatch.setenv("AIOPS_PERFIL", str(ruta))
    perfiles.activo()
    yield
    perfiles._cargar_y_activar.cache_clear()
    restaurar_catalogo()
    runtime.reset()


def _ciclo(entorno: Entorno, nivel: NivelAutonomia = NivelAutonomia.AUTONOMO_CON_ROLLBACK) -> Ciclo:
    politica = Politica(
        nivel=nivel,
        entornos_permitidos=frozenset({"qa"}),
        niveles_categoria=perfiles.activo().niveles,  # type: ignore[union-attr]
    )
    return Ciclo(entorno, entorno, politica, Auditoria())


def _abierto(ciclo: Ciclo, nombre: str) -> tuple[str, Alerta]:
    alerta = Alerta(f"{nombre}:web:1", nombre, "web", "qa", Severidad.MEDIA, "r", 1.0)
    return ciclo.abrir_desde_alerta(alerta).id, alerta


def _hasta_diagnostico(ciclo: Ciclo, nombre: str) -> str:
    inc, _ = _abierto(ciclo, nombre)
    ciclo.confirmar_anomalia(inc)
    ciclo.clasificar(inc)
    ciclo.registrar_diagnostico(inc, "causa", 0.95, "RB-001")
    return inc


@pytest.mark.usefixtures("perfil_activo")
def test_categoria_sin_nivel_queda_en_simulacro() -> None:
    entorno = Entorno()
    ciclo = _ciclo(entorno)
    res = ciclo.ejecutar_remediacion(_hasta_diagnostico(ciclo, "Observada"), aprobada=False)
    assert "SIMULACRO" in res.mensaje and not res.ejecutada
    assert entorno.acciones == []


@pytest.mark.usefixtures("perfil_activo")
def test_nivel_por_categoria_y_tope_global() -> None:
    entorno = Entorno()
    ciclo = _ciclo(entorno)
    res = ciclo.ejecutar_remediacion(_hasta_diagnostico(ciclo, "Autonoma"), aprobada=False)
    assert res.ejecutada and entorno.acciones == ["restart_service"]

    topado = Entorno()
    ciclo2 = _ciclo(topado, NivelAutonomia.RECOMIENDA)
    res2 = ciclo2.ejecutar_remediacion(_hasta_diagnostico(ciclo2, "Autonoma"), aprobada=False)
    assert "SIMULACRO" in res2.mensaje and topado.acciones == []


@pytest.mark.usefixtures("perfil_activo")
def test_el_entorno_acota_y_el_perfil_no_se_autoriza_solo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AIOPS_BACKEND", "prometheus")
    monkeypatch.setenv("AIOPS_PROMETHEUS_URL", "http://p")
    monkeypatch.setenv("AIOPS_ACTIONS", "ninguna")
    monkeypatch.setenv("AIOPS_ALLOWED_ENVS", "dev")
    monkeypatch.setenv("AIOPS_AUTONOMY_LEVEL", "4")
    politica = runtime.armar(persistencia="memoria").politica
    assert politica.entornos_permitidos == frozenset()
    assert politica.nivel_de("sin_nivel") is NivelAutonomia.RECOMIENDA
    assert politica.nivel_de("autonoma") is NivelAutonomia.AUTONOMO_CON_ROLLBACK


def test_sin_niveles_por_categoria_rige_el_global() -> None:
    p = Politica(nivel=NivelAutonomia.AUTONOMO_BAJO_RIESGO)
    assert p.nivel_de("cualquiera") is NivelAutonomia.AUTONOMO_BAJO_RIESGO


@pytest.mark.usefixtures("perfil_activo")
def test_alerta_desconocida_no_puede_actuar_ni_con_el_nivel_maximo() -> None:
    entorno = Entorno()
    ciclo = _ciclo(entorno)
    inc, _ = _abierto(ciclo, "NoCatalogada")
    with pytest.raises(ErrorCiclo):
        ciclo.ejecutar_remediacion(inc, aprobada=False)
    assert (
        ciclo.politica.evaluar(ciclo.incidente(inc), None, "restart_service").veredicto
        is Veredicto.DENEGAR
    )
    assert ciclo.logs(inc, 5) == ["linea"]
    assert entorno.acciones == []


def test_el_investigador_no_recibe_tools_que_remedian(monkeypatch: pytest.MonkeyPatch) -> None:
    capturado: dict[str, Any] = {}

    def falso(modelo: Any, herramientas: list[Any], **kw: Any) -> str:
        capturado["tools"] = {t.__name__ for t in herramientas}
        return "agente"

    monkeypatch.setattr("langchain.agents.create_agent", falso)
    assert agente.construir_investigador("modelo") == "agente"
    assert capturado["tools"] <= agente.SOLO_LECTURA
    assert "escalar_a_humano" in capturado["tools"] and "consultar_logs" in capturado["tools"]
    assert not any(n.startswith(("ejecutar", "revertir", "cerrar")) for n in capturado["tools"])


def _llm_falso(monkeypatch: pytest.MonkeyPatch, invocar: Any) -> list[str]:
    usados: list[str] = []

    class Falso:
        def __init__(self, nombre: str) -> None:
            self.nombre = nombre

        def invoke(self, entrada: Any, config: Any = None) -> dict[str, Any]:
            usados.append(self.nombre)
            invocar(entrada["messages"][0]["content"])
            return {"messages": []}

    monkeypatch.setattr(agente, "construir", lambda m=None: Falso("completo"))
    monkeypatch.setattr(agente, "construir_investigador", lambda m=None: Falso("investigador"))
    monkeypatch.setattr(agente, "modelo_por_defecto", lambda: "falso")
    monkeypatch.setattr("app.main.modelo_de_la_ui", lambda: None)
    monkeypatch.setattr("app.main.respaldo_de_la_ui", lambda: None)
    return usados


@pytest.mark.usefixtures("perfil_activo")
def test_worker_manda_lo_desconocido_al_investigador(monkeypatch: pytest.MonkeyPatch) -> None:
    entorno = Entorno()
    ciclo = _ciclo(entorno)
    inc, alerta = _abierto(ciclo, "NoCatalogada")
    usados = _llm_falso(monkeypatch, lambda _: None)
    worker_jobs.atender_con_agente(ciclo, inc, alerta)
    assert usados == ["investigador"]
    assert ciclo.incidente(inc).estado is Estado.ESCALADO  # no abandona aunque el LLM no escale
    assert entorno.acciones == []


def test_sin_perfil_lo_desconocido_sigue_el_camino_de_siempre(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AIOPS_PERFIL", raising=False)
    entorno = Entorno()
    ciclo = Ciclo(entorno, entorno, Politica(), Auditoria())
    inc, alerta = _abierto(ciclo, "NoCatalogada")
    usados = _llm_falso(monkeypatch, lambda _: None)
    worker_jobs.atender_con_agente(ciclo, inc, alerta)
    assert usados == ["completo"]


@pytest.mark.usefixtures("perfil_activo")
def test_nivel_2_queda_pendiente_y_se_retoma_tras_aprobar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entorno = Entorno()
    ciclo = _ciclo(entorno)
    inc = _hasta_diagnostico(ciclo, "Aprobada")
    runtime.reset(ciclo)

    # Primer turno: pide aprobacion, queda pendiente y no se abandona ni se escala.
    assert ciclo.ejecutar_remediacion(inc, aprobada=False).veredicto is Veredicto.APROBACION
    assert tools.ejecutar_remediacion_con_aprobacion(inc).startswith("PENDIENTE")
    worker_jobs._cerrar_cabos_sueltos(ciclo, inc, {"messages": []})
    assert ciclo.incidente(inc).estado is Estado.DIAGNOSTICADO and entorno.acciones == []

    # Sin aprobacion, el job de retomar no hace nada.
    monkeypatch.setattr(runtime, "armar", lambda persistencia=None: ciclo)
    monkeypatch.setattr(worker_jobs, "bloqueo_servicio", _sin_bloqueo)
    assert "nada que retomar" in worker_jobs.reanudar_aprobado(inc)

    ciclo.aprobar(inc, "ana")

    def retoma(pedido: str) -> None:
        assert "APROBO" in pedido
        tools.ejecutar_remediacion_con_aprobacion(inc)
        tools.escalar_a_humano(inc, "fin de la prueba")

    _llm_falso(monkeypatch, retoma)
    assert "retomado" in worker_jobs.reanudar_aprobado(inc)
    assert entorno.acciones == ["restart_service"]
    assert ciclo.incidente(inc).intervencion_humana is True
    # Una vez ejecutada, otro job (reintento o doble clic) no vuelve a actuar.
    assert "nada que retomar" in worker_jobs.reanudar_aprobado(inc)
    assert entorno.acciones == ["restart_service"]


class _sin_bloqueo:  # noqa: N801
    def __init__(self, servicio: str) -> None:
        pass

    def __enter__(self) -> None:
        pass

    def __exit__(self, *a: object) -> None:
        pass
