"""Evals de resultado conocido sobre el banco simulado. No invocan el LLM: recorren el
ciclo con las mismas tools que el agente llama, asi que si el LLM sigue el prompt el
resultado es predecible. Incluye el calculo de TRA de la tesis sobre un lote."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from agents.aiops import runtime, tools
from domain.aiops_core.auditoria import Auditoria
from domain.aiops_core.ciclo import Ciclo
from domain.aiops_core.metricas import tasa_resolucion_autonoma
from domain.aiops_core.modelos import NivelAutonomia
from domain.aiops_core.politicas import Politica
from domain.aiops_core.simulador import EntornoSimulado

RUNBOOK = {
    "servicio_detenido": "RB-001",
    "disco_lleno": "RB-002",
    "pod_fallido": "RB-003",
    "cola_detenida": "RB-004",
    "certificado_por_vencer": "RB-005",
}


@pytest.fixture
def entorno() -> Iterator[EntornoSimulado]:
    env = EntornoSimulado()
    runtime.reset(Ciclo(env, env, Politica(nivel=NivelAutonomia.AUTONOMO_BAJO_RIESGO), Auditoria()))
    yield env
    runtime.reset()


def recorrer(alerta_id: str, categoria: str) -> str:
    """El camino que pide prompt.md, devolviendo el estado final textual."""
    inc_id = tools.abrir_incidente(alerta_id).split()[0]
    if "CONFIRMADA" not in tools.confirmar_anomalia(inc_id).split(":")[0]:
        return tools.descartar_falso_positivo(inc_id)
    clasif = tools.clasificar_incidente(inc_id)
    if "NO elegible" in clasif:
        return tools.escalar_a_humano(inc_id, clasif)
    tools.registrar_diagnostico(inc_id, "causa conocida", 0.9, RUNBOOK[categoria])
    res = tools.ejecutar_remediacion(inc_id)
    if res.startswith("DENEGADO"):
        return tools.escalar_a_humano(inc_id, res)
    if tools.verificar_recuperacion(inc_id).startswith("RECUPERADO"):
        return tools.cerrar_incidente(inc_id)
    tools.revertir_accion(inc_id)
    return tools.escalar_a_humano(inc_id, "no recuperado")


@pytest.mark.eval
@pytest.mark.parametrize(
    "categoria", ["servicio_detenido", "disco_lleno", "pod_fallido", "cola_detenida"]
)
def test_l1_remediable_se_resuelve_solo(entorno: EntornoSimulado, categoria: str) -> None:
    alerta = entorno.inyectar_fallo("svc", categoria)
    assert "RESUELTO de forma autonoma" in recorrer(alerta.id, categoria)
    assert tools.listar_alertas_activas() == "Sin alertas activas."


@pytest.mark.eval
def test_certificado_se_escala(entorno: EntornoSimulado) -> None:
    alerta = entorno.inyectar_fallo("gw", "certificado_por_vencer")
    assert recorrer(alerta.id, "certificado_por_vencer").startswith("ESCALADO")


@pytest.mark.eval
def test_accion_ineficaz_se_escala(entorno: EntornoSimulado) -> None:
    entorno.acciones_efectivas = False
    alerta = entorno.inyectar_fallo("svc", "servicio_detenido")
    assert recorrer(alerta.id, "servicio_detenido").startswith("ESCALADO")


@pytest.mark.eval
def test_tools_devuelven_error_legible(entorno: EntornoSimulado) -> None:
    assert tools.abrir_incidente("NOPE").startswith("ERROR:")
    alerta = entorno.inyectar_fallo("svc", "servicio_detenido")
    inc_id = tools.abrir_incidente(alerta.id).split()[0]
    assert "verificada" in tools.cerrar_incidente(inc_id)
    assert inc_id in tools.estado_incidente(inc_id)


@pytest.mark.eval
def test_lote_tra_supera_objetivo_de_la_tesis(entorno: EntornoSimulado) -> None:
    """5 remediables + 1 ineficaz: TRA = 4/5 elegibles (el certificado no es elegible)."""
    lote = [
        ("a", "servicio_detenido"),
        ("b", "disco_lleno"),
        ("c", "pod_fallido"),
        ("d", "cola_detenida"),
        ("e", "certificado_por_vencer"),
    ]
    for servicio, categoria in lote:
        recorrer(entorno.inyectar_fallo(servicio, categoria).id, categoria)
    entorno.acciones_efectivas = False
    recorrer(entorno.inyectar_fallo("f", "servicio_detenido").id, "servicio_detenido")
    tra = tasa_resolucion_autonoma(runtime.get_ciclo().incidentes())
    assert tra == pytest.approx(80.0)
    assert tra >= 30  # criterio de exito H1 (en simulacion, no evidencia real)
