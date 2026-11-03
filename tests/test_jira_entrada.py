"""Un ticket se vuelve Alerta: etiquetas primero, LLM de respaldo y SIEMPRE validacion del
dominio. Lo que no valida queda fuera del catalogo (se escala); el texto se sanea."""

from __future__ import annotations

import pytest

from agents.aiops import jira_entrada
from agents.aiops.jira_entrada import alerta_desde_ticket, clasificar
from domain.aiops_core.catalogo import CATALOGO
from domain.aiops_core.modelos import Severidad
from infra.jira import Ticket


def _t(etiquetas: tuple[str, ...] = (), prioridad: str = "Medium", titulo: str = "algo") -> Ticket:
    return Ticket("OPS-1", titulo, "detalle", etiquetas, prioridad, 1000.0)


def test_etiquetas_mandan_y_no_llaman_al_llm() -> None:
    def llm(titulo: str, descripcion: str) -> tuple[str | None, str | None]:
        raise AssertionError("no debia llamarse")

    t = _t(("servicio:checkout", "categoria:servicio_detenido"))
    assert clasificar(t, llm) == ("checkout", "servicio_detenido", "etiquetas")
    a = alerta_desde_ticket(t, llm)
    assert a.id == "JIRA-OPS-1" and a.servicio == "checkout"
    assert a.nombre == CATALOGO["servicio_detenido"].alertas[0]
    assert a.disparada_en == 1000.0 and a.entorno == "staging"


def test_sin_etiquetas_usa_el_llm_pero_el_dominio_valida() -> None:
    assert clasificar(_t(), lambda t, d: ("api", "pod_fallido")) == ("api", "pod_fallido", "llm")
    fuera = alerta_desde_ticket(_t(), lambda t, d: ("bd-prod", "borrar_todo"))
    assert fuera.nombre == jira_entrada.NOMBRE_FUERA_DE_CATALOGO


def test_sin_etiquetas_ni_llm_queda_fuera_del_catalogo() -> None:
    a = alerta_desde_ticket(_t(), None)
    assert a.nombre == "JiraTicket" and a.servicio == "desconocido"


def test_servicio_desconocido_aunque_venga_en_etiqueta(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIOPS_SERVICIOS", "api")
    a = alerta_desde_ticket(_t(("servicio:checkout", "categoria:servicio_detenido")))
    assert a.nombre == "JiraTicket"


def test_nombre_de_servicio_hostil_no_pasa() -> None:
    a = alerta_desde_ticket(_t(("servicio:checkout;rm -rf", "categoria:servicio_detenido")))
    assert a.servicio == "desconocido" and a.nombre == "JiraTicket"


@pytest.mark.parametrize(
    ("prioridad", "severidad"),
    [("Highest", Severidad.CRITICA), ("High", Severidad.ALTA), ("Medium", Severidad.MEDIA),
     ("Low", Severidad.BAJA), ("rara", Severidad.MEDIA)],
)  # fmt: skip
def test_prioridad_a_severidad(prioridad: str, severidad: Severidad) -> None:
    assert alerta_desde_ticket(_t(prioridad=prioridad)).severidad is severidad


def test_resumen_saneado_y_acotado() -> None:
    t = _t(titulo="caido password=hunter2 " + "x" * 500)
    a = alerta_desde_ticket(t)
    assert "hunter2" not in a.resumen and len(a.resumen) <= 200 and a.resumen.startswith("OPS-1")


def test_entorno_solo_de_la_configuracion(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AIOPS_JIRA_ENTORNO", raising=False)
    assert alerta_desde_ticket(_t()).entorno == "staging"
    monkeypatch.setenv("AIOPS_JIRA_ENTORNO", "prod")
    # una etiqueta del ticket no puede rebajar el entorno que fijo el admin
    assert alerta_desde_ticket(_t(("entorno:dev",))).entorno == "prod"


def test_llm_que_falla_no_rompe() -> None:
    def roto(t: str, d: str) -> tuple[str | None, str | None]:
        raise RuntimeError("proveedor caido")

    assert clasificar(_t(), roto) == (None, None, "ninguno")
