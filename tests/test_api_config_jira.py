"""Endpoints de Jira: token de admin, el token de Jira nunca sale por la API, y el servidor
resuelve los estados de cada columna desde Jira (no confia en ids del navegador)."""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.api import app
from infra.jira import ErrorJira
from infra.jira_config import Columna

ADMIN = {"Authorization": "Bearer admin-token"}
TOKEN = "ATATT3x-token-jira-de-prueba-4321"


class JiraFalso:
    def __init__(self, *a: Any, **k: Any) -> None:
        pass

    def yo(self) -> str:
        return "Ops Bot"

    def tableros(self) -> list[dict[str, Any]]:
        return [{"id": 7, "nombre": "OPS"}]

    def columnas(self, tablero_id: int) -> list[Columna]:
        return [Columna("Por hacer", ("10000",)), Columna("Listo", ("10002",))]


@pytest.fixture
def cliente(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("AIOPS_API_TOKEN", "test-token")
    monkeypatch.setenv("AIOPS_ADMIN_TOKEN", "admin-token")
    monkeypatch.setenv("AIOPS_SECRETS_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr("app.api._cliente_jira", lambda: JiraFalso())
    monkeypatch.setattr("agents.aiops.jira_poller.programar", lambda s=None: True)
    yield TestClient(app)
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        conn.execute(
            "UPDATE aiops_jira_config SET sitio = NULL, correo = NULL, token_cifrado = NULL, "
            "sufijo = NULL, tablero_id = NULL, tablero_nombre = NULL, entrada = NULL, "
            "resuelto = NULL, escalado = NULL, intervalo_s = 60, activo = false"
        )
        conn.execute("DELETE FROM aiops_eventos_auditoria WHERE incidente_id = 'config:jira'")


def _conectar(c: TestClient) -> Any:
    return c.put(
        "/config/jira/conexion",
        headers=ADMIN,
        json={"sitio": "https://acme.atlassian.net", "correo": "ops@acme.cl",
              "token": TOKEN, "usuario": "ana"},
    )  # fmt: skip


def test_solo_admin(cliente: TestClient) -> None:
    operador = {"Authorization": "Bearer test-token"}
    assert cliente.get("/config/jira").status_code == 401
    assert cliente.get("/config/jira", headers=operador).status_code == 401
    assert cliente.get("/config/jira", headers=ADMIN).status_code == 200


def test_flujo_completo_sin_filtrar_el_token(cliente: TestClient) -> None:
    r = _conectar(cliente)
    assert r.status_code == 200 and TOKEN not in r.text and r.json()["sufijo"] == "4321"
    probar = cliente.post("/config/jira/probar", headers=ADMIN)
    assert probar.json() == {"ok": True, "detalle": "Ops Bot"}
    tableros = cliente.get("/config/jira/tableros", headers=ADMIN)
    assert tableros.json() == [{"id": 7, "nombre": "OPS"}]
    cols = cliente.get("/config/jira/tableros/7/columnas", headers=ADMIN).json()
    assert cols == [
        {"nombre": "Por hacer", "estados": ["10000"]},
        {"nombre": "Listo", "estados": ["10002"]},
    ]
    r = cliente.put(
        "/config/jira/tablero",
        headers=ADMIN,
        json={"tablero_id": 7, "entrada": "Por hacer", "resuelto": "Listo", "escalado": None,
              "intervalo_s": 60, "usuario": "ana"},
    )  # fmt: skip
    assert r.status_code == 200 and r.json()["tablero_nombre"] == "OPS"
    r = cliente.put("/config/jira/activo", headers=ADMIN, json={"activo": True, "usuario": "ana"})
    assert r.status_code == 200 and r.json()["activo"] is True
    assert TOKEN not in cliente.get("/config/jira", headers=ADMIN).text


def test_columna_inventada_por_el_navegador_se_rechaza(cliente: TestClient) -> None:
    _conectar(cliente)
    r = cliente.put(
        "/config/jira/tablero",
        headers=ADMIN,
        json={"tablero_id": 7, "entrada": "Inventada", "intervalo_s": 60, "usuario": "ana"},
    )
    assert r.status_code == 422 and "Inventada" in r.text


def test_errores_de_validacion_y_de_jira(
    cliente: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    r = cliente.put(
        "/config/jira/conexion",
        headers=ADMIN,
        json={"sitio": "https://evil.com", "correo": "a@b.c", "token": "x", "usuario": "ana"},
    )
    assert r.status_code == 422
    r = cliente.put("/config/jira/activo", headers=ADMIN, json={"activo": True, "usuario": "ana"})
    assert r.status_code == 422

    class Caido(JiraFalso):
        def yo(self) -> str:
            raise ErrorJira("Jira respondio 401 en GET /rest/api/2/myself")

    _conectar(cliente)
    monkeypatch.setattr("app.api._cliente_jira", lambda: Caido())
    assert cliente.post("/config/jira/probar", headers=ADMIN).json()["ok"] is False
