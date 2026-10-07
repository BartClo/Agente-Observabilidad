"""Configuracion del LLM del agente desde la UI: proveedor, modelo y API key.

- Proveedores soportados: Anthropic, OpenAI, Google Gemini y DeepSeek (integraciones de
  LangChain, todas con tool calling, que deepagents necesita).
- La API key se guarda CIFRADA (Fernet) en Postgres con la clave maestra
  AIOPS_SECRETS_KEY, que vive solo en el entorno. Sin esa clave no se guarda nada.
- Ninguna funcion publica devuelve la key: el estado expone solo si esta configurada y
  sus ultimos 4 caracteres.
- Sin proveedor activo, el agente usa el modelo de agent.yaml / ORCHESTRATOR_MODEL
  (comportamiento anterior).
- Cada cambio queda en aiops_eventos_auditoria (incidente_id "config:llm").

Tablas: migrations/versions/b7c2e1f4a9d0_config_llm.py.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import psycopg
from psycopg.types.json import Jsonb

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel


class ConfigLLMError(ValueError):
    """Pedido invalido (proveedor desconocido, key vacia, falta la clave maestra...)."""


@dataclass(frozen=True)
class Proveedor:
    id: str
    nombre: str
    langchain: str  # model_provider de langchain.chat_models.init_chat_model
    ejemplo: str  # solo una pista para la UI: se valida con "Probar conexion"


PROVEEDORES: dict[str, Proveedor] = {
    p.id: p
    for p in (
        Proveedor("anthropic", "Anthropic", "anthropic", "claude-sonnet-5-5"),
        Proveedor("openai", "OpenAI", "openai", "ver docs de OpenAI"),
        Proveedor("google", "Google Gemini", "google_genai", "ver docs de Gemini"),
        Proveedor("deepseek", "DeepSeek", "deepseek", "ver docs de DeepSeek"),
    )
}

_MODELO_VALIDO = re.compile(r"^[A-Za-z0-9._:/@-]{1,120}$")
_MAX_KEY = 1000


def _url(database_url: str | None) -> str:
    return database_url or os.environ["DATABASE_URL"]


def _fernet() -> Any:
    from cryptography.fernet import Fernet

    clave = os.environ.get("AIOPS_SECRETS_KEY", "").strip()
    if not clave:
        raise ConfigLLMError(
            "AIOPS_SECRETS_KEY no configurada: sin clave maestra no se guardan API keys"
        )
    try:
        return Fernet(clave.encode())
    except ValueError as exc:
        raise ConfigLLMError("AIOPS_SECRETS_KEY invalida (debe ser una clave Fernet)") from exc


def _proveedor(proveedor: str) -> Proveedor:
    try:
        return PROVEEDORES[proveedor]
    except KeyError:
        raise ConfigLLMError(f"proveedor desconocido: {proveedor!r}") from None


def _auditar(conn: psycopg.Connection[Any], tipo: str, **datos: Any) -> None:
    conn.execute(
        "INSERT INTO aiops_eventos_auditoria (ts, incidente_id, tipo, datos) "
        "VALUES (now(), 'config:llm', %s, %s)",
        (tipo, Jsonb(datos)),
    )


def guardar_api_key(
    proveedor: str, api_key: str, usuario: str, database_url: str | None = None
) -> None:
    prov = _proveedor(proveedor)
    key = api_key.strip()
    if not key or len(key) > _MAX_KEY:
        raise ConfigLLMError("API key vacia o demasiado larga")
    cifrada = _fernet().encrypt(key.encode()).decode()
    with psycopg.connect(_url(database_url), autocommit=True) as conn:
        conn.execute(
            "INSERT INTO aiops_llm_credenciales (proveedor, api_key_cifrada, sufijo, "
            "actualizado_por, actualizado_en) VALUES (%s, %s, %s, %s, now()) "
            "ON CONFLICT (proveedor) DO UPDATE SET api_key_cifrada = EXCLUDED.api_key_cifrada, "
            "sufijo = EXCLUDED.sufijo, actualizado_por = EXCLUDED.actualizado_por, "
            "actualizado_en = now()",
            (prov.id, cifrada, key[-4:], usuario),
        )
        _auditar(conn, "llm_key_guardada", proveedor=prov.id, usuario=usuario)


def borrar_api_key(proveedor: str, usuario: str, database_url: str | None = None) -> None:
    prov = _proveedor(proveedor)
    with psycopg.connect(_url(database_url), autocommit=True) as conn:
        conn.execute("DELETE FROM aiops_llm_credenciales WHERE proveedor = %s", (prov.id,))
        # Si era el proveedor activo, se vuelve al modelo por defecto: nunca dejar al
        # agente apuntando a un proveedor sin credencial.
        conn.execute(
            "UPDATE aiops_llm_activo SET proveedor = NULL, modelo = NULL, actualizado_por = %s, "
            "actualizado_en = now() WHERE id = true AND proveedor = %s",
            (usuario, prov.id),
        )
        _auditar(conn, "llm_key_borrada", proveedor=prov.id, usuario=usuario)


def seleccionar(
    proveedor: str | None, modelo: str | None, usuario: str, database_url: str | None = None
) -> None:
    """Elige el proveedor y el modelo que usa el agente. `proveedor=None` vuelve al
    modelo por defecto (agent.yaml / ORCHESTRATOR_MODEL)."""
    with psycopg.connect(_url(database_url), autocommit=True) as conn:
        if proveedor is None:
            conn.execute(
                "UPDATE aiops_llm_activo SET proveedor = NULL, modelo = NULL, "
                "actualizado_por = %s, actualizado_en = now() WHERE id = true",
                (usuario,),
            )
            _auditar(conn, "llm_seleccion", proveedor=None, modelo=None, usuario=usuario)
            return
        prov = _proveedor(proveedor)
        if not modelo or not _MODELO_VALIDO.fullmatch(modelo.strip()):
            raise ConfigLLMError("nombre de modelo invalido")
        tiene_key = conn.execute(
            "SELECT 1 FROM aiops_llm_credenciales WHERE proveedor = %s", (prov.id,)
        ).fetchone()
        if not tiene_key:
            raise ConfigLLMError(f"primero cargar la API key de {prov.nombre}")
        conn.execute(
            "UPDATE aiops_llm_activo SET proveedor = %s, modelo = %s, actualizado_por = %s, "
            "actualizado_en = now() WHERE id = true",
            (prov.id, modelo.strip(), usuario),
        )
        _auditar(conn, "llm_seleccion", proveedor=prov.id, modelo=modelo.strip(), usuario=usuario)


def estado(database_url: str | None = None) -> dict[str, Any]:
    """Lo que puede ver la UI. Nunca incluye una API key."""
    with psycopg.connect(_url(database_url), autocommit=True) as conn:
        creds = {
            fila[0]: fila[1:]
            for fila in conn.execute(
                "SELECT proveedor, sufijo, actualizado_por, actualizado_en "
                "FROM aiops_llm_credenciales"
            ).fetchall()
        }
        activo = conn.execute(
            "SELECT proveedor, modelo, actualizado_por, actualizado_en FROM aiops_llm_activo "
            "WHERE id = true"
        ).fetchone()
    return {
        "proveedores": [
            {
                "id": p.id,
                "nombre": p.nombre,
                "ejemplo": p.ejemplo,
                "configurada": p.id in creds,
                "sufijo": creds[p.id][0] if p.id in creds else None,
                "actualizado_por": creds[p.id][1] if p.id in creds else None,
                "actualizado_en": creds[p.id][2].isoformat() if p.id in creds else None,
            }
            for p in PROVEEDORES.values()
        ],
        "activo": {
            "proveedor": activo[0] if activo else None,
            "modelo": activo[1] if activo else None,
            "actualizado_por": activo[2] if activo else None,
        },
    }


def _credencial(proveedor: str, database_url: str | None) -> str:
    with psycopg.connect(_url(database_url), autocommit=True) as conn:
        fila = conn.execute(
            "SELECT api_key_cifrada FROM aiops_llm_credenciales WHERE proveedor = %s",
            (proveedor,),
        ).fetchone()
    if not fila:
        raise ConfigLLMError(f"no hay API key cargada para {proveedor}")
    from cryptography.fernet import InvalidToken

    try:
        return str(_fernet().decrypt(fila[0].encode()).decode())
    except InvalidToken as exc:
        raise ConfigLLMError(
            "no se pudo descifrar la API key: AIOPS_SECRETS_KEY cambio desde que se guardo. "
            "Volver a cargar la key."
        ) from exc


def construir(proveedor: str, modelo: str, api_key: str) -> BaseChatModel:
    from langchain.chat_models import init_chat_model

    return init_chat_model(modelo, model_provider=_proveedor(proveedor).langchain, api_key=api_key)


def modelo_activo(database_url: str | None = None) -> tuple[BaseChatModel, str] | None:
    """(modelo listo para deepagents, etiqueta "proveedor:modelo") o None si no hay uno
    elegido en la UI (se usa el modelo por defecto)."""
    with psycopg.connect(_url(database_url), autocommit=True) as conn:
        fila = conn.execute(
            "SELECT proveedor, modelo FROM aiops_llm_activo WHERE id = true"
        ).fetchone()
    if not fila or not fila[0]:
        return None
    proveedor, modelo = fila
    return construir(
        proveedor, modelo, _credencial(proveedor, database_url)
    ), f"{proveedor}:{modelo}"


def probar(proveedor: str, modelo: str, database_url: str | None = None) -> tuple[bool, str]:
    """Una llamada minima con la key guardada, para validar key y nombre de modelo antes
    de usarlos en un incidente. El error del proveedor se recorta y nunca incluye la key."""
    if not _MODELO_VALIDO.fullmatch(modelo.strip()):
        return False, "nombre de modelo invalido"
    api_key = _credencial(_proveedor(proveedor).id, database_url)
    try:
        respuesta = construir(proveedor, modelo.strip(), api_key).invoke("Responde solo: ok")
    except Exception as exc:
        detalle = str(exc).replace(api_key, "***")[:300]
        return False, f"{type(exc).__name__}: {detalle}"
    return True, f"respondio: {str(respuesta.content)[:80]!r}"
