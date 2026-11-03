"""Configuracion de Jira desde la UI: el token queda cifrado, nunca sale por el estado y
la configuracion incompleta no activa el poller. Integracion contra la base de tests."""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from cryptography.fernet import Fernet

from infra import jira_config
from infra.jira_config import Columna, ConfigJiraError

TOKEN = "ATATT3xFfGF0-token-de-prueba-9z8y"


@pytest.fixture(autouse=True)
def _limpio(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("AIOPS_SECRETS_KEY", Fernet.generate_key().decode())
    yield
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        conn.execute(
            "UPDATE aiops_jira_config SET sitio = NULL, correo = NULL, token_cifrado = NULL, "
            "sufijo = NULL, tablero_id = NULL, tablero_nombre = NULL, entrada = NULL, "
            "resuelto = NULL, escalado = NULL, intervalo_s = 60, activo = false, "
            "ultimo_sondeo_en = NULL, ultimo_sondeo_tickets = NULL, ultimo_error = NULL"
        )
        conn.execute("DELETE FROM aiops_eventos_auditoria WHERE incidente_id = 'config:jira'")


def _filas(sql: str) -> list[Any]:
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        return conn.execute(sql).fetchall()


def _completa() -> None:
    jira_config.guardar_conexion("https://acme.atlassian.net", "ops@acme.cl", TOKEN, "ana")
    jira_config.guardar_tablero(
        7, "OPS", Columna("Por hacer", ("10000",)), Columna("Listo", ("10002",)),
        Columna("Revision", ("10003",)), 60, "ana",
    )  # fmt: skip


def test_token_cifrado_y_nunca_en_el_estado() -> None:
    jira_config.guardar_conexion("https://acme.atlassian.net", "ops@acme.cl", f" {TOKEN}\n", "ana")
    ((cifrado, sufijo),) = _filas("SELECT token_cifrado, sufijo FROM aiops_jira_config")
    assert TOKEN not in cifrado and sufijo == "9z8y"
    estado = jira_config.estado()
    assert TOKEN not in str(estado) and estado["sufijo"] == "9z8y" and estado["configurada"]
    assert jira_config.credenciales() == ("https://acme.atlassian.net", "ops@acme.cl", TOKEN)
    assert TOKEN not in str(_filas("SELECT datos FROM aiops_eventos_auditoria"))


def test_token_vacio_conserva_el_guardado() -> None:
    jira_config.guardar_conexion("https://acme.atlassian.net", "ops@acme.cl", TOKEN, "ana")
    jira_config.guardar_conexion("https://otra.atlassian.net", "ops@acme.cl", "", "ana")
    assert jira_config.credenciales() == ("https://otra.atlassian.net", "ops@acme.cl", TOKEN)


@pytest.mark.parametrize(
    "sitio",
    ["http://acme.atlassian.net", "https://acme.atlassian.net/", "https://evil.com",
     "https://acme.atlassian.net.evil.com", "https://jira.acme.cl"],
)  # fmt: skip
def test_solo_sitios_de_jira_cloud(sitio: str) -> None:
    with pytest.raises(ConfigJiraError, match="sitio"):
        jira_config.guardar_conexion(sitio, "ops@acme.cl", TOKEN, "ana")


def test_primera_conexion_exige_token_y_clave_maestra(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ConfigJiraError, match="token"):
        jira_config.guardar_conexion("https://acme.atlassian.net", "ops@acme.cl", "", "ana")
    monkeypatch.delenv("AIOPS_SECRETS_KEY")
    with pytest.raises(ConfigJiraError, match="AIOPS_SECRETS_KEY"):
        jira_config.guardar_conexion("https://acme.atlassian.net", "ops@acme.cl", TOKEN, "ana")


def test_cargar_solo_con_configuracion_completa() -> None:
    assert jira_config.cargar() is None
    _completa()
    cfg = jira_config.cargar()
    assert cfg is not None and cfg.token == TOKEN and cfg.tablero_id == 7
    assert cfg.entrada == Columna("Por hacer", ("10000",)) and not cfg.activo
    jira_config.activar(True, "ana")
    assert jira_config.cargar().activo  # type: ignore[union-attr]


def test_no_se_activa_sin_tablero() -> None:
    jira_config.guardar_conexion("https://acme.atlassian.net", "ops@acme.cl", TOKEN, "ana")
    with pytest.raises(ConfigJiraError, match="tablero"):
        jira_config.activar(True, "ana")


def test_valida_intervalo_y_estados() -> None:
    jira_config.guardar_conexion("https://acme.atlassian.net", "ops@acme.cl", TOKEN, "ana")
    with pytest.raises(ConfigJiraError, match="intervalo"):
        jira_config.guardar_tablero(7, "OPS", Columna("A", ("1",)), None, None, 10, "ana")
    with pytest.raises(ConfigJiraError, match="estado"):
        jira_config.guardar_tablero(7, "OPS", Columna("A", ("1 OR 1=1",)), None, None, 60, "ana")
    with pytest.raises(ConfigJiraError, match="entrada"):
        jira_config.guardar_tablero(7, "OPS", Columna("A", ()), None, None, 60, "ana")


def test_registrar_sondeo_aparece_en_el_estado() -> None:
    _completa()
    jira_config.registrar_sondeo(2, None)
    estado = jira_config.estado()
    assert estado["ultimo_sondeo_tickets"] == 2 and estado["ultimo_error"] is None
    assert estado["ultimo_sondeo_en"] is not None
    jira_config.registrar_sondeo(0, "Jira respondio 401")
    assert jira_config.estado()["ultimo_error"] == "Jira respondio 401"
