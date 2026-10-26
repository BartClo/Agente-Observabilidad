"""Configuracion del LLM desde la UI: la API key nunca queda en claro ni sale por el
estado; el agente usa el proveedor/modelo elegidos. Integracion contra Postgres (base
de tests, ver conftest.py)."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from cryptography.fernet import Fernet

from infra import llm_config
from infra.llm_config import ConfigLLMError

KEY = "sk-ant-secreta-de-prueba-a3f9"


@pytest.fixture(autouse=True)
def _limpio(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("AIOPS_SECRETS_KEY", Fernet.generate_key().decode())
    yield
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        conn.execute("DELETE FROM aiops_llm_credenciales")
        conn.execute(
            "UPDATE aiops_llm_activo SET proveedor = NULL, modelo = NULL, "
            "respaldo_proveedor = NULL, respaldo_modelo = NULL WHERE id = true"
        )
        conn.execute("DELETE FROM aiops_eventos_auditoria WHERE incidente_id = 'config:llm'")


def _filas(sql: str) -> list[Any]:
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        return conn.execute(sql).fetchall()


def test_sin_clave_maestra_no_guarda_nada(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AIOPS_SECRETS_KEY")
    with pytest.raises(ConfigLLMError, match="AIOPS_SECRETS_KEY"):
        llm_config.guardar_api_key("anthropic", KEY, "admin")
    assert _filas("SELECT * FROM aiops_llm_credenciales") == []


def test_key_cifrada_en_la_base_y_nunca_en_el_estado() -> None:
    llm_config.guardar_api_key("anthropic", f"  {KEY}\n", "admin")
    ((cifrada, sufijo),) = _filas("SELECT api_key_cifrada, sufijo FROM aiops_llm_credenciales")
    assert KEY not in cifrada and sufijo == "a3f9"
    estado = llm_config.estado()
    assert KEY not in json.dumps(estado)
    anth = next(p for p in estado["proveedores"] if p["id"] == "anthropic")
    assert anth["configurada"] and anth["sufijo"] == "a3f9" and anth["actualizado_por"] == "admin"
    assert not next(p for p in estado["proveedores"] if p["id"] == "openai")["configurada"]
    # auditado, sin la key
    eventos = _filas(
        "SELECT tipo, datos FROM aiops_eventos_auditoria WHERE incidente_id = 'config:llm'"
    )
    assert [e[0] for e in eventos] == ["llm_key_guardada"] and KEY not in json.dumps(eventos[0][1])


def test_seleccionar_exige_key_y_el_agente_usa_el_modelo_elegido() -> None:
    with pytest.raises(ConfigLLMError, match="primero cargar"):
        llm_config.seleccionar("deepseek", "deepseek-chat", "admin")
    assert llm_config.modelo_activo() is None  # sin seleccion: modelo por defecto

    llm_config.guardar_api_key("deepseek", "sk-deepseek-1234", "admin")
    llm_config.seleccionar("deepseek", "deepseek-chat", "admin")
    resultado = llm_config.modelo_activo()
    assert resultado is not None
    modelo, etiqueta = resultado
    assert etiqueta == "deepseek:deepseek-chat"
    assert type(modelo).__name__ == "ChatDeepSeek"
    assert modelo.api_key.get_secret_value() == "sk-deepseek-1234"  # type: ignore[attr-defined]

    with pytest.raises(ConfigLLMError, match="modelo invalido"):
        llm_config.seleccionar("deepseek", "modelo con espacios; rm -rf", "admin")
    llm_config.seleccionar(None, None, "admin")
    assert llm_config.modelo_activo() is None


@pytest.mark.parametrize(
    ("proveedor", "clase"),
    [
        ("anthropic", "ChatAnthropic"),
        ("openai", "ChatOpenAI"),
        ("google", "ChatGoogleGenerativeAI"),
        ("deepseek", "ChatDeepSeek"),
    ],
)
def test_los_cuatro_proveedores(proveedor: str, clase: str) -> None:
    llm_config.guardar_api_key(proveedor, "clave-1234", "admin")
    llm_config.seleccionar(proveedor, "modelo-x", "admin")
    resultado = llm_config.modelo_activo()
    assert resultado is not None and type(resultado[0]).__name__ == clase


def test_borrar_la_key_del_proveedor_activo_vuelve_al_default() -> None:
    llm_config.guardar_api_key("openai", "sk-openai-9999", "admin")
    llm_config.seleccionar("openai", "modelo-x", "admin")
    llm_config.borrar_api_key("openai", "admin")
    assert llm_config.modelo_activo() is None
    assert llm_config.estado()["activo"]["proveedor"] is None


def test_clave_maestra_cambiada_da_error_claro(monkeypatch: pytest.MonkeyPatch) -> None:
    llm_config.guardar_api_key("google", "AIza-1234", "admin")
    llm_config.seleccionar("google", "modelo-x", "admin")
    monkeypatch.setenv("AIOPS_SECRETS_KEY", Fernet.generate_key().decode())
    with pytest.raises(ConfigLLMError, match="Volver a cargar"):
        llm_config.modelo_activo()


def test_probar_no_filtra_la_key_en_el_error(monkeypatch: pytest.MonkeyPatch) -> None:
    llm_config.guardar_api_key("anthropic", KEY, "admin")

    class Falla:
        def invoke(self, _: str) -> Any:
            raise RuntimeError(f"401 invalid x-api-key: {KEY}")

    monkeypatch.setattr(llm_config, "construir", lambda *a: Falla())
    ok, detalle = llm_config.probar("anthropic", "claude-x")
    assert not ok and KEY not in detalle and "***" in detalle
    assert llm_config.probar("anthropic", "mal modelo") == (False, "nombre de modelo invalido")


def test_validaciones() -> None:
    with pytest.raises(ConfigLLMError, match="desconocido"):
        llm_config.guardar_api_key("mistral", "k", "admin")
    with pytest.raises(ConfigLLMError, match="vacia"):
        llm_config.guardar_api_key("openai", "   ", "admin")
    with pytest.raises(ConfigLLMError, match="no hay API key"):
        llm_config.probar("openai", "modelo-x")


def test_el_cliente_del_llm_tiene_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """RNF de confiabilidad: ningun proveedor queda sin timeout (todos aceptan el kwarg)."""
    monkeypatch.setenv("AIOPS_LLM_TIMEOUT_S", "7")
    for proveedor in llm_config.PROVEEDORES:
        modelo = llm_config.construir(proveedor, "modelo-x", "clave-1234")
        # cada integracion lo guarda con su nombre (Anthropic: default_request_timeout)
        nombres = ("request_timeout", "default_request_timeout", "timeout")
        assert 7.0 in {getattr(modelo, a, None) for a in nombres}, proveedor
        assert modelo.max_retries == 2, proveedor  # type: ignore[attr-defined]


def test_respaldo_exige_key_y_distinto_del_principal() -> None:
    assert llm_config.modelo_respaldo() is None
    with pytest.raises(ConfigLLMError, match="primero cargar"):
        llm_config.seleccionar_respaldo("google", "gemini-x", "admin")
    llm_config.guardar_api_key("deepseek", "sk-deepseek-1234", "admin")
    llm_config.guardar_api_key("google", "AIza-5678", "admin")
    llm_config.seleccionar("deepseek", "deepseek-chat", "admin")
    with pytest.raises(ConfigLLMError, match="mismo modelo"):
        llm_config.seleccionar_respaldo("deepseek", "deepseek-chat", "admin")
    with pytest.raises(ConfigLLMError, match="modelo invalido"):
        llm_config.seleccionar_respaldo("google", "malo; x", "admin")

    llm_config.seleccionar_respaldo("google", "gemini-x", "admin")
    modelo, etiqueta = llm_config.modelo_respaldo()  # type: ignore[misc]
    assert etiqueta == "google:gemini-x" and type(modelo).__name__ == "ChatGoogleGenerativeAI"
    assert llm_config.estado()["respaldo"] == {"proveedor": "google", "modelo": "gemini-x"}
    # el principal sigue siendo el principal
    assert llm_config.estado()["activo"]["proveedor"] == "deepseek"
    llm_config.seleccionar_respaldo(None, None, "admin")
    assert llm_config.modelo_respaldo() is None


def test_borrar_la_key_del_respaldo_lo_quita() -> None:
    llm_config.guardar_api_key("google", "AIza-5678", "admin")
    llm_config.seleccionar_respaldo("google", "gemini-x", "admin")
    llm_config.borrar_api_key("google", "admin")
    assert llm_config.estado()["respaldo"] == {"proveedor": None, "modelo": None}


def test_api_key_devuelve_la_key_descifrada() -> None:
    llm_config.guardar_api_key("anthropic", KEY, "admin")
    assert llm_config.api_key("anthropic") == KEY
    with pytest.raises(ConfigLLMError, match="no hay API key"):
        llm_config.api_key("openai")
