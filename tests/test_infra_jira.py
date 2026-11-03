"""ClienteJira con HTTP falso: rutas y verbos correctos, Basic auth, JQL armada solo con
ids validados, y cualquier falla de red o HTTP como ErrorJira (el poller la registra)."""

from __future__ import annotations

import base64
import io
import json
import urllib.error
import urllib.parse
from typing import Any

import pytest

from infra.jira import ClienteJira, ErrorJira
from infra.jira_config import Columna


class _Resp(io.BytesIO):
    def __enter__(self) -> _Resp:
        return self

    def __exit__(self, *a: object) -> None:
        pass


ISSUE = {
    "key": "OPS-12",
    "fields": {
        "summary": "checkout no responde",
        "description": {"type": "doc", "content": [{"type": "paragraph", "content": [
            {"type": "text", "text": "Desde las 10:00 "}, {"type": "text", "text": "da 502"}]}]},
        "labels": ["servicio:checkout", "categoria:servicio_detenido"],
        "priority": {"name": "High"},
        "created": "2026-11-03T10:00:00.000-0300",
    },
}  # fmt: skip


@pytest.fixture
def http(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    pedidos: list[Any] = []

    def falso(req: Any, timeout: float) -> _Resp:
        pedidos.append(req)
        url = req.full_url
        if "rechazo" in url:
            raise urllib.error.HTTPError(url, 401, "Unauthorized", {}, None)  # type: ignore[arg-type]
        if "caido" in url:
            raise urllib.error.URLError("timed out")
        if url.endswith("/rest/api/2/myself"):
            return _Resp(json.dumps({"displayName": "Ops Bot"}).encode())
        if "/rest/agile/1.0/board?" in url:
            return _Resp(json.dumps({"values": [{"id": 7, "name": "OPS"}]}).encode())
        if url.endswith("/configuration"):
            cols = [
                {"name": "Por hacer", "statuses": [{"id": "10000"}]},
                {"name": "Listo", "statuses": [{"id": "10002"}, {"id": "10005"}]},
            ]
            return _Resp(json.dumps({"columnConfig": {"columns": cols}}).encode())
        if "/issue?" in url:
            return _Resp(json.dumps({"issues": [ISSUE]}).encode())
        if url.endswith("/transitions") and req.get_method() == "GET":
            trans = [{"id": "31", "to": {"id": "10002"}}, {"id": "41", "to": {"id": "10003"}}]
            return _Resp(json.dumps({"transitions": trans}).encode())
        return _Resp(b"")

    monkeypatch.setattr("urllib.request.urlopen", falso)
    return pedidos


def _cliente(sitio: str = "https://acme.atlassian.net") -> ClienteJira:
    return ClienteJira(sitio, "ops@acme.cl", "tok")


def test_basic_auth_y_yo(http: list[Any]) -> None:
    assert _cliente().yo() == "Ops Bot"
    esperado = "Basic " + base64.b64encode(b"ops@acme.cl:tok").decode()
    assert http[0].headers["Authorization"] == esperado


def test_tableros_y_columnas(http: list[Any]) -> None:
    assert _cliente().tableros() == [{"id": 7, "nombre": "OPS"}]
    assert _cliente().columnas(7) == [
        Columna("Por hacer", ("10000",)),
        Columna("Listo", ("10002", "10005")),
    ]
    assert http[1].full_url.endswith("/rest/agile/1.0/board/7/configuration")


def test_tickets_arma_la_jql_con_los_ids_y_lee_adf(http: list[Any]) -> None:
    (t,) = _cliente().tickets(7, ("10000", "10001"), 5)
    consulta = urllib.parse.parse_qs(urllib.parse.urlsplit(http[0].full_url).query)
    assert consulta["jql"] == ["status in (10000,10001) ORDER BY created ASC"]
    assert http[0].full_url.startswith("https://acme.atlassian.net/rest/agile/1.0/board/7/issue?")
    assert t.clave == "OPS-12" and t.titulo == "checkout no responde"
    assert t.descripcion == "Desde las 10:00 da 502" and t.prioridad == "High"
    assert t.etiquetas == ("servicio:checkout", "categoria:servicio_detenido")
    assert t.creado == pytest.approx(1793710800.0)


def test_estados_no_numericos_no_llegan_a_la_jql(http: list[Any]) -> None:
    with pytest.raises(ErrorJira, match="estado"):
        _cliente().tickets(7, ("10000) OR project = X",), 5)
    assert http == []


def test_comentar_y_transicionar_solo_al_estado_configurado(http: list[Any]) -> None:
    c = _cliente()
    c.comentar("OPS-12", "hola")
    assert http[0].get_method() == "POST"
    assert http[0].full_url.endswith("/rest/api/2/issue/OPS-12/comment")
    assert json.loads(http[0].data) == {"body": "hola"}
    assert c.transicionar("OPS-12", ("10003",)) is True
    assert json.loads(http[-1].data) == {"transition": {"id": "41"}}
    assert c.transicionar("OPS-12", ("99999",)) is False  # sin transicion posible: no inventa


def test_clave_invalida_no_se_usa_en_la_ruta(http: list[Any]) -> None:
    with pytest.raises(ErrorJira, match="clave"):
        _cliente().comentar("../../admin", "x")
    assert http == []


def test_errores_http_y_de_red_son_error_jira_sin_el_token(http: list[Any]) -> None:
    with pytest.raises(ErrorJira, match="401") as exc:
        _cliente("https://rechazo.atlassian.net").yo()
    assert "tok" not in str(exc.value)
    with pytest.raises(ErrorJira, match="no responde"):
        _cliente("https://caido.atlassian.net").yo()
