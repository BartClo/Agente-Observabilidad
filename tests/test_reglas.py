"""El comparador por reglas: siempre actua, reintenta dentro del limite y escala."""

from __future__ import annotations

from domain.aiops_core.auditoria import Auditoria
from domain.aiops_core.ciclo import Ciclo
from domain.aiops_core.modelos import Estado, NivelAutonomia, Severidad
from domain.aiops_core.politicas import Politica
from domain.aiops_core.reglas import atender_con_reglas
from domain.aiops_core.simulador import EntornoSimulado


def _armar(env: EntornoSimulado, categoria: str = "pod_fallido") -> tuple[Ciclo, str]:
    alerta = env.inyectar_fallo("checkout", categoria, Severidad.MEDIA)
    ciclo = Ciclo(env, env, Politica(nivel=NivelAutonomia.AUTONOMO_BAJO_RIESGO), Auditoria())
    return ciclo, ciclo.abrir(alerta.id).id


def test_resuelve_una_falla_limpia_sin_llm() -> None:
    ciclo, inc_id = _armar(EntornoSimulado())
    atender_con_reglas(ciclo, inc_id)
    inc = ciclo.incidente(inc_id)
    assert inc.estado is Estado.RESUELTO and inc.confianza == 0.9 and len(inc.acciones) == 1


def test_categoria_sin_accion_escala_sin_actuar() -> None:
    ciclo, inc_id = _armar(EntornoSimulado(), "certificado_por_vencer")
    atender_con_reglas(ciclo, inc_id)
    inc = ciclo.incidente(inc_id)
    assert inc.estado is Estado.ESCALADO and not inc.acciones


def test_causa_que_la_accion_no_arregla_reintenta_hasta_el_limite_y_escala() -> None:
    class Terco(EntornoSimulado):
        """Falla que la accion no recupera: una variante confusora."""

        def metrica(self, servicio: str, nombre: str) -> float | None:
            return 0.0 if nombre == "pod_ready" else super().metrica(servicio, nombre)

    ciclo, inc_id = _armar(Terco())
    atender_con_reglas(ciclo, inc_id)
    inc = ciclo.incidente(inc_id)
    assert inc.estado is Estado.ESCALADO and len(inc.acciones) == 2  # max_reintentos = 2
