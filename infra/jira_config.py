"""Configuracion de Jira Cloud desde la UI: sitio, correo, API token y tablero.

- El token se guarda CIFRADO (Fernet, misma clave maestra AIOPS_SECRETS_KEY que las API keys
  del LLM). Ninguna funcion publica salvo `credenciales()`/`cargar()` (uso interno del poller)
  devuelve el token; el estado expone solo si esta configurado y sus ultimos 4 caracteres.
- Los estados de cada columna son ids numericos validados: con ellos el sistema arma la JQL.
- Cada cambio queda en aiops_eventos_auditoria (incidente_id "config:jira"), sin el token.

Tablas: migrations/versions/f6a1c9d2e4b7_jira.py.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from infra.llm_config import ConfigLLMError, _fernet

_SITIO = re.compile(r"^https://[a-z0-9][a-z0-9-]{0,62}\.atlassian\.net$")
_CORREO = re.compile(r"^[^@\s]{1,100}@[^@\s]{1,150}$")
_ESTADO = re.compile(r"^\d{1,10}$")
_MAX_TOKEN = 1000
INTERVALO_MIN_S = 30


class ConfigJiraError(ValueError):
    """Pedido invalido (sitio fuera de Jira Cloud, token vacio, falta la clave maestra...)."""


@dataclass(frozen=True)
class Columna:
    nombre: str
    estados: tuple[str, ...]


@dataclass(frozen=True)
class ConfigJira:
    sitio: str
    correo: str
    token: str
    tablero_id: int
    entrada: Columna
    resuelto: Columna | None
    escalado: Columna | None
    intervalo_s: int
    activo: bool


def _url(database_url: str | None) -> str:
    return database_url or os.environ["DATABASE_URL"]


def _cifrador() -> Any:
    try:
        return _fernet()
    except ConfigLLMError as exc:
        raise ConfigJiraError(str(exc)) from exc


def _auditar(conn: psycopg.Connection[Any], tipo: str, **datos: Any) -> None:
    conn.execute(
        "INSERT INTO aiops_eventos_auditoria (ts, incidente_id, tipo, datos) "
        "VALUES (now(), 'config:jira', %s, %s)",
        (tipo, Jsonb(datos)),
    )


def _a_json(columna: Columna | None) -> Jsonb | None:
    if columna is None:
        return None
    return Jsonb({"nombre": columna.nombre, "estados": list(columna.estados)})


def _de_json(dato: Any) -> Columna | None:
    if not dato:
        return None
    return Columna(str(dato["nombre"]), tuple(str(e) for e in dato["estados"]))


def _validar_columna(columna: Columna | None, rotulo: str, obligatoria: bool) -> None:
    if columna is None:
        if obligatoria:
            raise ConfigJiraError(f"falta la columna de {rotulo}")
        return
    if not columna.estados:
        raise ConfigJiraError(f"la columna de {rotulo} no tiene estados")
    for e in columna.estados:
        if not _ESTADO.fullmatch(e):
            raise ConfigJiraError(f"estado invalido en la columna de {rotulo}: {e!r}")


def guardar_conexion(
    sitio: str, correo: str, token: str, usuario: str, database_url: str | None = None
) -> None:
    """`token` vacio conserva el ya guardado (para cambiar sitio o correo sin repegarlo)."""
    sitio, correo, token = sitio.strip(), correo.strip(), token.strip()
    if not _SITIO.fullmatch(sitio):
        raise ConfigJiraError("sitio invalido: debe ser https://<nombre>.atlassian.net")
    if not _CORREO.fullmatch(correo):
        raise ConfigJiraError("correo invalido")
    if len(token) > _MAX_TOKEN:
        raise ConfigJiraError("token demasiado largo")
    with psycopg.connect(_url(database_url), autocommit=True) as conn:
        if token:
            cifrado = _cifrador().encrypt(token.encode()).decode()
            conn.execute(
                "UPDATE aiops_jira_config SET sitio = %s, correo = %s, token_cifrado = %s, "
                "sufijo = %s, actualizado_por = %s, actualizado_en = now() WHERE id = true",
                (sitio, correo, cifrado, token[-4:], usuario),
            )
        else:
            fila = conn.execute(
                "SELECT token_cifrado FROM aiops_jira_config WHERE id = true"
            ).fetchone()
            if fila is None or not fila[0]:
                raise ConfigJiraError("falta el token: la primera conexion lo exige")
            conn.execute(
                "UPDATE aiops_jira_config SET sitio = %s, correo = %s, actualizado_por = %s, "
                "actualizado_en = now() WHERE id = true",
                (sitio, correo, usuario),
            )
        _auditar(conn, "jira_conexion_guardada", sitio=sitio, usuario=usuario)


def credenciales(database_url: str | None = None) -> tuple[str, str, str]:
    with psycopg.connect(_url(database_url), autocommit=True) as conn:
        fila = conn.execute(
            "SELECT sitio, correo, token_cifrado FROM aiops_jira_config WHERE id = true"
        ).fetchone()
    if fila is None or not all(fila):
        raise ConfigJiraError("Jira no configurado: guardar sitio, correo y token")
    sitio, correo, cifrado = fila
    return sitio, correo, _cifrador().decrypt(cifrado.encode()).decode()


def guardar_tablero(
    tablero_id: int,
    tablero_nombre: str,
    entrada: Columna,
    resuelto: Columna | None,
    escalado: Columna | None,
    intervalo_s: int,
    usuario: str,
    database_url: str | None = None,
) -> None:
    if tablero_id <= 0:
        raise ConfigJiraError("tablero invalido")
    if intervalo_s < INTERVALO_MIN_S:
        raise ConfigJiraError(f"intervalo minimo: {INTERVALO_MIN_S} s")
    _validar_columna(entrada, "entrada", obligatoria=True)
    _validar_columna(resuelto, "resuelto", obligatoria=False)
    _validar_columna(escalado, "escalado", obligatoria=False)
    with psycopg.connect(_url(database_url), autocommit=True) as conn:
        conn.execute(
            "UPDATE aiops_jira_config SET tablero_id = %s, tablero_nombre = %s, entrada = %s, "
            "resuelto = %s, escalado = %s, intervalo_s = %s, actualizado_por = %s, "
            "actualizado_en = now() WHERE id = true",
            (
                tablero_id,
                tablero_nombre[:200],
                _a_json(entrada),
                _a_json(resuelto),
                _a_json(escalado),
                intervalo_s,
                usuario,
            ),
        )
        _auditar(conn, "jira_tablero_guardado", tablero_id=tablero_id, usuario=usuario)


def activar(activo: bool, usuario: str, database_url: str | None = None) -> None:
    if activo and cargar(database_url) is None:
        raise ConfigJiraError("no se puede activar: falta la conexion o el tablero")
    with psycopg.connect(_url(database_url), autocommit=True) as conn:
        conn.execute(
            "UPDATE aiops_jira_config SET activo = %s, actualizado_por = %s, "
            "actualizado_en = now() WHERE id = true",
            (activo, usuario),
        )
        _auditar(conn, "jira_activado" if activo else "jira_pausado", usuario=usuario)


def cargar(database_url: str | None = None) -> ConfigJira | None:
    """Configuracion completa (con el token en claro, solo para el poller) o None."""
    with psycopg.connect(_url(database_url), autocommit=True) as conn:
        fila = conn.execute(
            "SELECT sitio, correo, token_cifrado, tablero_id, entrada, resuelto, escalado, "
            "intervalo_s, activo FROM aiops_jira_config WHERE id = true"
        ).fetchone()
    if fila is None:
        return None
    sitio, correo, cifrado, tablero_id, entrada, resuelto, escalado, intervalo_s, activo = fila
    columna_entrada = _de_json(entrada)
    if not (sitio and correo and cifrado and tablero_id and columna_entrada):
        return None
    return ConfigJira(
        sitio=sitio,
        correo=correo,
        token=_cifrador().decrypt(cifrado.encode()).decode(),
        tablero_id=int(tablero_id),
        entrada=columna_entrada,
        resuelto=_de_json(resuelto),
        escalado=_de_json(escalado),
        intervalo_s=int(intervalo_s),
        activo=bool(activo),
    )


def estado(database_url: str | None = None) -> dict[str, Any]:
    with psycopg.connect(_url(database_url), autocommit=True) as conn:
        fila = conn.execute(
            "SELECT sitio, correo, sufijo, tablero_id, tablero_nombre, entrada, resuelto, "
            "escalado, intervalo_s, activo, actualizado_por, ultimo_sondeo_en, "
            "ultimo_sondeo_tickets, ultimo_error FROM aiops_jira_config WHERE id = true"
        ).fetchone()
    if fila is None:
        return {"configurada": False}
    (sitio, correo, sufijo, tablero_id, tablero_nombre, entrada, resuelto, escalado,
     intervalo_s, activo, por, sondeo_en, sondeo_n, error) = fila  # fmt: skip
    return {
        "configurada": bool(sitio and sufijo),
        "sitio": sitio,
        "correo": correo,
        "sufijo": sufijo,
        "tablero_id": tablero_id,
        "tablero_nombre": tablero_nombre,
        "entrada": entrada and entrada["nombre"],
        "resuelto": resuelto and resuelto["nombre"],
        "escalado": escalado and escalado["nombre"],
        "intervalo_s": intervalo_s,
        "activo": activo,
        "actualizado_por": por,
        "ultimo_sondeo_en": sondeo_en.isoformat() if sondeo_en else None,
        "ultimo_sondeo_tickets": sondeo_n,
        "ultimo_error": error,
    }


def registrar_sondeo(tickets: int, error: str | None, database_url: str | None = None) -> None:
    with psycopg.connect(_url(database_url), autocommit=True) as conn:
        conn.execute(
            "UPDATE aiops_jira_config SET ultimo_sondeo_en = now(), ultimo_sondeo_tickets = %s, "
            "ultimo_error = %s WHERE id = true",
            (tickets, error[:300] if error else None),
        )
