"""Chat de consulta (agents/aiops/chat.py y POST /chat, GET /eventos): solo lectura,
recuerda la conversacion en Postgres y los avisos salen de la auditoria sin LLM."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from agents.aiops import chat, runtime
from tests.test_api import HEADERS, cliente  # noqa: F401  (fixture)


class ModeloFalso(GenericFakeChatModel):
    """Responde una secuencia fija; acepta tools (create_agent llama a bind_tools)."""

    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
        return self


@pytest.fixture
def _limpia_checkpoints() -> Iterator[None]:
    yield
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        conn.execute("DELETE FROM checkpoints WHERE thread_id LIKE 'chat:%'")
        conn.execute("DELETE FROM checkpoint_writes WHERE thread_id LIKE 'chat:%'")
        conn.execute("DELETE FROM checkpoint_blobs WHERE thread_id LIKE 'chat:%'")


def _incidente() -> str:
    ciclo = runtime.get_ciclo()
    inc = ciclo.abrir(ciclo.alertas_activas()[0].split(" | ")[0])
    ciclo.confirmar_anomalia(inc.id)
    return inc.id


def test_el_chat_no_tiene_tools_de_escritura() -> None:
    nombres = {t.__name__ for t in chat.TOOLS}
    assert nombres == {
        "listar_incidentes",
        "ver_incidente",
        "ver_metricas",
        "capacidades",
        "leer_runbook",
    }


def test_tools_de_lectura(cliente: TestClient) -> None:  # noqa: F811
    inc_id = _incidente()
    listado = json.loads(chat.listar_incidentes())
    assert [i["id"] for i in listado] == [inc_id]
    assert chat.listar_incidentes(estado="resuelto") == "Sin incidentes."
    detalle = json.loads(chat.ver_incidente(inc_id))
    assert any(e["tipo"] == "confirmacion" for e in detalle["linea_de_tiempo"])
    assert chat.ver_incidente("INC-no").startswith("ERROR")
    assert json.loads(chat.ver_metricas())["total_incidentes"] == 1
    caps = json.loads(chat.capacidades())
    assert caps["nivel_autonomia"] == 3 and len(caps["catalogo"]) == 5
    assert caps["kill_switch_activo"] is False


def test_leer_runbook() -> None:
    assert "recreate_pod" in chat.leer_runbook(" rb-003 ")
    assert chat.leer_runbook("RB-999").startswith("No existe")


def test_responder_usa_tools_y_recuerda_la_conversacion(
    cliente: TestClient,  # noqa: F811
    _limpia_checkpoints: None,
) -> None:
    inc_id = _incidente()
    modelo = ModeloFalso(
        messages=iter(
            [
                AIMessage("", tool_calls=[{"name": "listar_incidentes", "args": {}, "id": "t1"}]),
                AIMessage(f"Hay un incidente: {inc_id}"),
                AIMessage("Sigue abierto."),
            ]
        )
    )
    assert chat.responder("conv-test-0001", "¿que incidentes hay?", modelo) == (
        f"Hay un incidente: {inc_id}"
    )
    assert chat.responder("conv-test-0001", "¿y como sigue?", modelo) == "Sigue abierto."
    # La conversacion quedo en Postgres: pregunta, tool call, resultado de la tool (con
    # el incidente real), respuesta, 2da pregunta y 2da respuesta.
    from infra.checkpointer import crear_checkpointer

    with crear_checkpointer() as cp:
        tupla = cp.get_tuple({"configurable": {"thread_id": "chat:conv-test-0001"}})
    assert tupla is not None
    mensajes = tupla.checkpoint["channel_values"]["messages"]
    assert [m.type for m in mensajes] == ["human", "ai", "tool", "ai", "human", "ai"]
    assert inc_id in mensajes[2].content


def test_endpoint_chat(cliente: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    monkeypatch.setattr(chat, "responder", lambda c, m, modelo: f"eco: {m}")
    r = cliente.post(
        "/chat", headers=HEADERS, json={"conversacion": "abcd-1234", "mensaje": " hola "}
    )
    assert r.json() == {"respuesta": "eco: hola"}
    for body in (
        {"conversacion": "corta", "mensaje": "hola"},
        {"conversacion": "abcd-1234; drop", "mensaje": "hola"},
        {"conversacion": "abcd-1234", "mensaje": "   "},
        {"conversacion": "abcd-1234", "mensaje": "x" * 4001},
    ):
        assert cliente.post("/chat", headers=HEADERS, json=body).status_code == 422
    assert (
        cliente.post("/chat", json={"conversacion": "abcd-1234", "mensaje": "h"}).status_code == 401
    )

    def caido(*a: Any) -> str:
        raise ConnectionError("proveedor caido")

    monkeypatch.setattr(chat, "responder", caido)
    r = cliente.post("/chat", headers=HEADERS, json={"conversacion": "abcd-1234", "mensaje": "h"})
    assert r.status_code == 502 and "ConnectionError" in r.text


def test_eventos_son_el_feed_de_avisos(cliente: TestClient) -> None:  # noqa: F811
    inc_id = _incidente()
    eventos = cliente.get("/eventos", headers=HEADERS).json()
    assert [e["tipo"] for e in eventos if e["incidente"] == inc_id][:2] == [
        "abierto",
        "confirmacion",
    ]
    ultimo = eventos[-1]["ts"]
    assert cliente.get(f"/eventos?desde={ultimo}", headers=HEADERS).json() == []


def test_eventos_en_modo_memoria(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api import app

    monkeypatch.setenv("AIOPS_API_TOKEN", "test-token")
    monkeypatch.setenv("AIOPS_SIM_FAULTS", "servicio_detenido:checkout")
    monkeypatch.delenv("AIOPS_PERSISTENCIA", raising=False)
    runtime.reset()
    try:
        _incidente()
        eventos = TestClient(app).get("/eventos?limite=1", headers=HEADERS).json()
        assert [e["tipo"] for e in eventos] == ["confirmacion"]
    finally:
        runtime.reset()
