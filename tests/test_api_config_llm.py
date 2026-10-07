"""Endpoints de configuracion del LLM: token de admin aparte, la key nunca sale por la
API y el modelo elegido es el que usa el agente (app/main.py)."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app import main
from app.api import app
from infra import llm_config

ADMIN = {"Authorization": "Bearer admin-token"}
KEY = "sk-secreta-de-prueba-7777"


@pytest.fixture
def cliente(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("AIOPS_API_TOKEN", "test-token")
    monkeypatch.setenv("AIOPS_ADMIN_TOKEN", "admin-token")
    monkeypatch.setenv("AIOPS_SECRETS_KEY", Fernet.generate_key().decode())
    yield TestClient(app)
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        conn.execute("DELETE FROM aiops_llm_credenciales")
        conn.execute("UPDATE aiops_llm_activo SET proveedor = NULL, modelo = NULL WHERE id = true")
        conn.execute("DELETE FROM aiops_eventos_auditoria WHERE incidente_id = 'config:llm'")


def test_el_token_de_operador_no_alcanza(cliente: TestClient) -> None:
    assert cliente.get("/config/llm").status_code == 401
    operador = {"Authorization": "Bearer test-token"}
    assert cliente.get("/config/llm", headers=operador).status_code == 401
    assert cliente.get("/config/llm", headers=ADMIN).status_code == 200


def test_sin_admin_token_configurado_falla_cerrado(
    cliente: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("AIOPS_ADMIN_TOKEN")
    assert cliente.get("/config/llm", headers=ADMIN).status_code == 500


def test_flujo_completo_sin_filtrar_la_key(cliente: TestClient) -> None:
    r = cliente.put(
        "/config/llm/credenciales/openai", headers=ADMIN, json={"api_key": KEY, "usuario": "ana"}
    )
    assert r.status_code == 200 and KEY not in r.text
    r = cliente.put(
        "/config/llm/activo",
        headers=ADMIN,
        json={"proveedor": "openai", "modelo": "modelo-x", "usuario": "ana"},
    )
    assert r.json()["activo"] == {
        "proveedor": "openai",
        "modelo": "modelo-x",
        "actualizado_por": "ana",
    }
    assert KEY not in json.dumps(cliente.get("/config/llm", headers=ADMIN).json())

    # El agente usa el modelo elegido (orquestador y subagentes).
    activo = main.modelo_de_la_ui()
    assert activo is not None and activo[1] == "openai:modelo-x"
    assert type(activo[0]).__name__ == "ChatOpenAI"

    r = cliente.delete("/config/llm/credenciales/openai?usuario=ana", headers=ADMIN)
    assert r.json()["activo"]["proveedor"] is None
    assert main.modelo_de_la_ui() is None


def test_errores_de_validacion_son_422(cliente: TestClient) -> None:
    casos: list[tuple[str, str, dict[str, Any]]] = [
        ("put", "/config/llm/credenciales/mistral", {"api_key": "k", "usuario": "ana"}),
        ("put", "/config/llm/credenciales/openai", {"usuario": "ana"}),
        ("put", "/config/llm/credenciales/openai", {"api_key": "k"}),
        ("put", "/config/llm/activo", {"proveedor": "openai", "modelo": "m", "usuario": "ana"}),
        ("post", "/config/llm/probar", {"proveedor": "openai"}),
        ("post", "/config/llm/probar", {"proveedor": "openai", "modelo": "m"}),
    ]
    for metodo, ruta, body in casos:
        r = getattr(cliente, metodo)(ruta, headers=ADMIN, json=body)
        assert r.status_code == 422, (ruta, body, r.text)


def test_probar_y_volver_al_default(cliente: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    cliente.put(
        "/config/llm/credenciales/google", headers=ADMIN, json={"api_key": KEY, "usuario": "ana"}
    )

    class Ok:
        content = "ok"

        def invoke(self, _: str) -> Any:
            return self

    monkeypatch.setattr(llm_config, "construir", lambda *a: Ok())
    r = cliente.post(
        "/config/llm/probar", headers=ADMIN, json={"proveedor": "google", "modelo": "g"}
    )
    assert r.json()["ok"] is True
    r = cliente.put("/config/llm/activo", headers=ADMIN, json={"proveedor": None, "usuario": "ana"})
    assert r.json()["activo"]["proveedor"] is None


def test_sin_base_de_datos_usa_el_modelo_por_defecto(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL")
    assert main.modelo_de_la_ui() is None
