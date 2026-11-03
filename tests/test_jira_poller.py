"""Poller de Jira: cada ticket una sola vez, por el mismo camino que el webhook; el
resultado vuelve como comentario + transicion, sin duplicar el comentario si la transicion
falla; AIOPS_JIRA=0 lo apaga. Jira falso; Postgres y Redis de tests reales."""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest

from agents.aiops import jira_poller
from domain.aiops_core.auditoria import Evento
from domain.aiops_core.modelos import AccionEjecutada, Alerta, Incidente, Severidad
from infra.jira import ErrorJira, Ticket
from infra.jira_config import Columna, ConfigJira

CFG = ConfigJira(
    "https://acme.atlassian.net", "ops@acme.cl", "tok", 7, Columna("Por hacer", ("10000",)),
    Columna("Listo", ("10002",)), Columna("Revision", ("10003",)), 60, True,
)  # fmt: skip


class JiraFalso:
    def __init__(self, tickets: list[Ticket]) -> None:
        self._tickets = tickets
        self.comentarios: list[tuple[str, str]] = []
        self.transiciones: list[tuple[str, tuple[str, ...]]] = []
        self.falla_comentar = False
        self.falla_transicion = False

    def tickets(self, tablero_id: int, estados: tuple[str, ...], maximo: int) -> list[Ticket]:
        return self._tickets[:maximo]

    def comentar(self, clave: str, texto: str) -> None:
        if self.falla_comentar:
            raise ErrorJira("Jira respondio 503")
        self.comentarios.append((clave, texto))

    def transicionar(self, clave: str, estados: tuple[str, ...]) -> bool:
        if self.falla_transicion:
            raise ErrorJira("Jira respondio 400")
        self.transiciones.append((clave, estados))
        return True


def _ticket(
    n: int, etiquetas: tuple[str, ...] = ("servicio:api", "categoria:pod_fallido")
) -> Ticket:
    return Ticket(f"OPS-{n}", f"ticket {n}", "", etiquetas, "Medium", 1000.0)


@pytest.fixture
def entorno(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Any]]:
    encoladas: list[Alerta] = []
    estado: dict[str, Any] = {"jira": JiraFalso([]), "sondeos": []}
    monkeypatch.setattr(jira_poller, "_cargar", lambda: CFG)
    monkeypatch.setattr(jira_poller, "_cliente", lambda cfg: estado["jira"])
    monkeypatch.setattr(jira_poller, "_clasificador", lambda: None)

    def encolar(alerta: Alerta) -> bool:
        encoladas.append(alerta)
        return True

    monkeypatch.setattr(jira_poller, "_encolar", encolar)
    monkeypatch.setattr(
        jira_poller, "_registrar_sondeo", lambda n, e: estado["sondeos"].append((n, e))
    )
    estado["encoladas"] = encoladas
    yield estado
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        conn.execute("DELETE FROM aiops_jira_tickets")


def _filas() -> list[Any]:
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        return conn.execute(
            "SELECT clave, estado, destino, intentos FROM aiops_jira_tickets ORDER BY clave"
        ).fetchall()


def test_cada_ticket_se_encola_una_sola_vez(entorno: dict[str, Any]) -> None:
    entorno["jira"] = JiraFalso([_ticket(1), _ticket(2)])
    assert jira_poller._sondear()["nuevos"] == ["OPS-1", "OPS-2"]
    assert jira_poller._sondear()["nuevos"] == []  # siguen en la columna: no se repiten
    assert [a.id for a in entorno["encoladas"]] == ["JIRA-OPS-1", "JIRA-OPS-2"]
    assert [f[:2] for f in _filas()] == [("OPS-1", "encolado"), ("OPS-2", "encolado")]
    assert entorno["sondeos"][-1] == (0, None)


def test_tope_de_tickets_nuevos_por_sondeo(entorno: dict[str, Any]) -> None:
    entorno["jira"] = JiraFalso([_ticket(n) for n in range(1, 9)])
    assert len(jira_poller._sondear()["nuevos"]) == jira_poller.MAX_POR_SONDEO
    assert len(jira_poller._sondear()["nuevos"]) == 3  # los que quedaron, en el siguiente


def test_error_de_jira_se_registra_y_no_explota(entorno: dict[str, Any]) -> None:
    class Caido(JiraFalso):
        def tickets(self, *a: Any) -> list[Ticket]:
            raise ErrorJira("Jira respondio 401 en GET /rest/agile/1.0/board/7/issue")

    entorno["jira"] = Caido([])
    assert "401" in jira_poller._sondear()["error"]
    assert "401" in entorno["sondeos"][-1][1]


def test_apagado_o_inactivo_no_consulta(
    entorno: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AIOPS_JIRA", "0")
    assert jira_poller._sondear() == {"omitido": "AIOPS_JIRA=0"}
    assert jira_poller.crear_sink() is None
    monkeypatch.delenv("AIOPS_JIRA")
    import dataclasses

    monkeypatch.setattr(jira_poller, "_cargar", lambda: dataclasses.replace(CFG, activo=False))
    assert jira_poller._sondear() == {"omitido": "inactivo"}


def _inc(estado_id: str = "INC-JIRA-OPS-1") -> Incidente:
    alerta = Alerta("JIRA-OPS-1", "PodFailed", "api", "staging", Severidad.MEDIA, "OPS-1: x")
    inc = Incidente(estado_id, alerta, 0.0, categoria_id="pod_fallido", causa="OOM", confianza=0.9)
    inc.acciones.append(AccionEjecutada("recreate_pod", "api", "ok", True))
    return inc


def test_comentario_sale_de_una_plantilla_y_saneado() -> None:
    texto = jira_poller.comentario("cerrado", {"autonomo": True}, _inc())
    assert "RESUELTO" in texto and "recreate_pod" in texto and "OOM" in texto
    hostil = jira_poller.comentario("escalado", {"motivo": "password=hunter2 [~admin]"}, _inc())
    assert "ESCALADO" in hostil and "hunter2" not in hostil


def test_sink_deja_pendiente_y_el_poller_comenta_y_transiciona(entorno: dict[str, Any]) -> None:
    entorno["jira"] = JiraFalso([_ticket(1)])
    jira_poller._sondear()
    sink = jira_poller.crear_sink(obtener_incidente=lambda i: _inc(), entregar=False)
    assert sink is not None
    sink(Evento(1.0, "INC-JIRA-OPS-1", "cerrado", {"autonomo": True}))
    sink(Evento(1.0, "INC-OTRO", "cerrado", {}))  # no es de Jira: se ignora
    assert _filas()[0][1:3] == ("pendiente", "resuelto")
    assert jira_poller.entregar_pendientes(entorno["jira"], CFG) == 1
    assert entorno["jira"].comentarios[0][0] == "OPS-1"
    assert entorno["jira"].transiciones == [("OPS-1", ("10002",))]
    assert _filas()[0][1] == "comentado"


def test_transicion_fallida_no_repite_el_comentario(entorno: dict[str, Any]) -> None:
    entorno["jira"] = JiraFalso([_ticket(1)])
    jira_poller._sondear()
    sink = jira_poller.crear_sink(obtener_incidente=lambda i: _inc(), entregar=False)
    assert sink is not None
    sink(Evento(1.0, "INC-JIRA-OPS-1", "escalado", {"motivo": "confianza baja"}))
    entorno["jira"].falla_transicion = True
    assert jira_poller.entregar_pendientes(entorno["jira"], CFG) == 1
    assert jira_poller.entregar_pendientes(entorno["jira"], CFG) == 0
    assert len(entorno["jira"].comentarios) == 1
    assert _filas()[0][1] == "comentado"


def test_comentario_fallido_se_reintenta(entorno: dict[str, Any]) -> None:
    entorno["jira"] = JiraFalso([_ticket(1)])
    jira_poller._sondear()
    sink = jira_poller.crear_sink(obtener_incidente=lambda i: _inc(), entregar=False)
    assert sink is not None
    sink(Evento(1.0, "INC-JIRA-OPS-1", "descartado", {}))
    entorno["jira"].falla_comentar = True
    assert jira_poller.entregar_pendientes(entorno["jira"], CFG) == 0
    assert _filas()[0][1:] == ("pendiente", "escalado", 1)
    entorno["jira"].falla_comentar = False
    assert jira_poller.entregar_pendientes(entorno["jira"], CFG) == 1


def test_programar_deja_un_solo_sondeo_agendado(
    entorno: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from infra.redis_client import get_redis

    get_redis().delete(jira_poller._CLAVE_PROXIMO)
    agendados: list[float] = []
    monkeypatch.setattr(jira_poller, "_agendar", lambda s: agendados.append(s))
    monkeypatch.setattr(jira_poller, "_hay_sondeo_agendado", lambda: False)
    assert jira_poller.programar(5) is True
    assert jira_poller.programar(5) is False  # el candado corto
    assert agendados == [5]
    get_redis().delete(jira_poller._CLAVE_PROXIMO)


def test_programar_no_agenda_si_ya_hay_uno_en_el_registro(
    entorno: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from infra.redis_client import get_redis

    get_redis().delete(jira_poller._CLAVE_PROXIMO)
    monkeypatch.setattr(jira_poller, "_hay_sondeo_agendado", lambda: True)
    monkeypatch.setattr(jira_poller, "_agendar", lambda s: pytest.fail("no debia agendar"))
    assert jira_poller.programar(5) is False
    get_redis().delete(jira_poller._CLAVE_PROXIMO)


def test_sondear_agenda_el_siguiente_antes_de_trabajar(
    entorno: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    orden: list[str] = []

    def programar(segundos: float | None = None) -> bool:
        orden.append("programar")
        return True

    def sondear() -> dict[str, Any]:
        orden.append("sondear")
        return {}

    monkeypatch.setattr(jira_poller, "programar", programar)
    monkeypatch.setattr(jira_poller, "_sondear", sondear)
    jira_poller.sondear()
    assert orden == ["programar", "sondear"]


def test_programar_con_cola_real_ve_el_sondeo_ya_agendado(
    entorno: dict[str, Any],
) -> None:
    from rq.registry import ScheduledJobRegistry

    from infra.queue import get_queue
    from infra.redis_client import get_redis

    def limpiar() -> None:
        cola = get_queue("aiops")
        registro = ScheduledJobRegistry(queue=cola)  # type: ignore[no-untyped-call]
        for job_id in registro.get_job_ids():
            registro.remove(job_id, delete_job=True)
        cola.empty()  # type: ignore[no-untyped-call]
        get_redis().delete(jira_poller._CLAVE_PROXIMO)

    limpiar()  # empty() no vacia los agendados: un job viejo haria fallar el test
    assert jira_poller.programar(300) is True
    get_redis().delete(jira_poller._CLAVE_PROXIMO)  # vence el candado corto
    assert jira_poller._hay_sondeo_agendado() is True
    assert jira_poller.programar(300) is False
    limpiar()


def test_ticket_cuyo_encolado_falla_se_reintenta_en_el_siguiente_sondeo(
    entorno: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    entorno["jira"] = JiraFalso([_ticket(1)])
    bueno = jira_poller._encolar

    def falla(alerta: Alerta) -> bool:
        raise RuntimeError("redis caido")

    monkeypatch.setattr(jira_poller, "_encolar", falla)
    assert jira_poller._sondear()["nuevos"] == []
    assert _filas() == []
    assert "redis caido" in entorno["sondeos"][-1][1]
    monkeypatch.setattr(jira_poller, "_encolar", bueno)
    assert jira_poller._sondear()["nuevos"] == ["OPS-1"]
