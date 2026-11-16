"""Sesion de la UI: un solo ingreso, el rol sale del token, la cookie solo vale con la
cabecera de la UI (CSRF) y rotar el token la invalida. Bearer sigue igual para maquinas."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient

from app import api
from app.api import app

UI = {"X-AIOPS-UI": "1"}


@pytest.fixture
def cliente(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("AIOPS_API_TOKEN", "op-token")
    monkeypatch.setenv("AIOPS_ADMIN_TOKEN", "admin-token")
    return TestClient(app)


def _entrar(c: TestClient, token: str, usuario: str = "ana") -> dict[str, str]:
    r = c.post("/sesion", json={"usuario": usuario, "token": token})
    assert r.status_code == 200, r.text
    datos: dict[str, str] = r.json()
    return datos


def test_el_rol_sale_del_token(cliente: TestClient) -> None:
    assert _entrar(cliente, "admin-token") == {"rol": "admin", "usuario": "ana"}
    assert cliente.get("/sesion", headers=UI).json() == {"rol": "admin", "usuario": "ana"}
    assert _entrar(cliente, "op-token")["rol"] == "operador"


def test_token_invalido_no_abre_sesion(cliente: TestClient) -> None:
    assert cliente.post("/sesion", json={"usuario": "ana", "token": "malo"}).status_code == 401
    assert cliente.post("/sesion", json={"usuario": "", "token": "op-token"}).status_code == 422
    assert cliente.post("/sesion", json={"usuario": "a|b", "token": "op-token"}).status_code == 422
    assert cliente.get("/sesion", headers=UI).status_code == 401


def test_la_cookie_es_httponly_y_strict(cliente: TestClient) -> None:
    r = cliente.post("/sesion", json={"usuario": "ana", "token": "op-token"})
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert "op-token" not in cookie


def test_operador_opera_pero_no_configura(cliente: TestClient) -> None:
    _entrar(cliente, "op-token")
    api.requiere_token(_peticion(cliente), None)  # no levanta: autorizado
    with pytest.raises(HTTPException) as exc:
        api.requiere_admin(_peticion(cliente), None)
    assert exc.value.status_code == 401


def test_admin_configura_y_opera(cliente: TestClient) -> None:
    _entrar(cliente, "admin-token")
    api.requiere_admin(_peticion(cliente), None)
    api.requiere_token(_peticion(cliente), None)


def test_sin_cabecera_de_la_ui_la_cookie_no_vale(cliente: TestClient) -> None:
    """Un formulario de otro sitio manda la cookie pero no puede mandar la cabecera."""
    _entrar(cliente, "admin-token")
    assert cliente.get("/sesion").status_code == 401
    with pytest.raises(HTTPException):
        api.requiere_admin(_peticion(cliente, cabecera=False), None)


def test_rotar_el_token_cierra_la_sesion(
    cliente: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _entrar(cliente, "admin-token")
    monkeypatch.setenv("AIOPS_ADMIN_TOKEN", "otro-token")
    assert cliente.get("/sesion", headers=UI).status_code == 401


def test_cookie_manipulada_o_vencida_no_vale(cliente: TestClient) -> None:
    _entrar(cliente, "op-token")
    rol, usuario, vence, firma = cliente.cookies["aiops_sesion"].strip('"').split("|")
    cliente.cookies.set("aiops_sesion", f"admin|{usuario}|{vence}|{firma}")
    assert cliente.get("/sesion", headers=UI).status_code == 401
    viejo = 1
    cliente.cookies.set(
        "aiops_sesion", f"{rol}|{usuario}|{viejo}|{api._firma(rol, usuario, viejo)}"
    )
    assert cliente.get("/sesion", headers=UI).status_code == 401


def test_salir_borra_la_cookie(cliente: TestClient) -> None:
    _entrar(cliente, "op-token")
    cliente.delete("/sesion")
    assert cliente.get("/sesion", headers=UI).status_code == 401


def test_bearer_sigue_igual(cliente: TestClient) -> None:
    api.requiere_token(_peticion(cliente, cabecera=False), "Bearer op-token")
    api.requiere_admin(_peticion(cliente, cabecera=False), "Bearer admin-token")
    with pytest.raises(HTTPException):
        api.requiere_admin(_peticion(cliente, cabecera=False), "Bearer op-token")


def test_la_ui_no_guarda_tokens_y_usa_la_sesion() -> None:
    html = (Path(api.__file__).parent / "ui" / "index.html").read_text("utf-8")
    assert 'id="admin-token"' not in html and "aiops-token" not in html
    assert '"X-AIOPS-UI": "1"' in html and 'api("/sesion")' in html
    assert "Guardar y probar" in html


def _peticion(c: TestClient, cabecera: bool = True) -> Request:
    """Request real con la cookie del cliente, para probar las dependencias directo."""
    cookie = (c.cookies.get("aiops_sesion") or "").strip('"')
    headers = [(b"cookie", f"aiops_sesion={cookie}".encode())]
    if cabecera:
        headers.append((b"x-aiops-ui", b"1"))
    return Request({"type": "http", "headers": headers})


def test_observabilidad_solo_admin_y_reporta_cada_fuente(
    cliente: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("AIOPS_LOKI_URL", raising=False)
    monkeypatch.setenv("AIOPS_PROMETHEUS_URL", "http://127.0.0.1:9")  # nada escucha
    assert (
        cliente.get(
            "/config/observabilidad", headers={"Authorization": "Bearer op-token"}
        ).status_code
        == 401
    )
    r = cliente.get(
        "/config/observabilidad", headers={"Authorization": "Bearer admin-token"}
    ).json()
    assert [s["nombre"] for s in r] == ["Prometheus", "Loki"]
    assert r[0]["ok"] is False and r[1] == {
        "nombre": "Loki",
        "url": None,
        "ok": None,
        "detalle": "no configurado",
    }


def test_la_ui_trae_la_puesta_en_marcha_y_las_tarjetas() -> None:
    html = (Path(api.__file__).parent / "ui" / "index.html").read_text("utf-8")
    for id_ in ("setup", "llm-provs", "llm-key", "sec-gchat", "sec-obs", "gchat-probar"):
        assert f'id="{id_}"' in html
    assert "llm-filas" not in html  # la tabla vieja de keys ya no existe
