"""Bandeja de salida (outbox) de notificaciones: entrega al menos una vez, sin perder
avisos si Google Chat esta caido.

Flujo: `encolar()` guarda el aviso en Postgres (tabla aiops_notificaciones, migracion
c3d8f2a6b1e4) y `entregar_pendientes()` lo manda con infra/gchat.py. Un fallo deja el
aviso `pendiente` con espera creciente (15 s, 30 s, 60 s... hasta 15 min); tras
MAX_INTENTOS pasa a `fallida` (visible en /metrics: aiops_notificaciones). Varios
procesos (worker, API) pueden entregar a la vez: cada fila se toma con
`FOR UPDATE SKIP LOCKED`, asi que nadie la manda dos veces.

Cortacircuito: tras un fallo no se vuelve a intentar durante PAUSA_S desde ese proceso,
para que un Google Chat caido no sume segundos de espera al MTTR de cada incidente.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import psycopg

from infra import gchat

logger = logging.getLogger(__name__)

MAX_INTENTOS = 8
PAUSA_S = 60.0
_ESPERA_BASE_S = 15
_ESPERA_MAX_S = 900

_pausa_hasta = 0.0


def _url(database_url: str | None) -> str:
    return database_url or os.environ["DATABASE_URL"]


def encolar(
    clave: str,
    incidente_id: str,
    tipo: str,
    texto: str,
    database_url: str | None = None,
) -> bool:
    """Guarda el aviso. False si ya existia (misma `clave`): no se duplica."""
    with psycopg.connect(_url(database_url), autocommit=True) as conn:
        fila = conn.execute(
            "INSERT INTO aiops_notificaciones (clave, incidente_id, tipo, texto) "
            "VALUES (%s, %s, %s, %s) ON CONFLICT (clave) DO NOTHING RETURNING id",
            (clave, incidente_id, tipo, texto),
        ).fetchone()
    return fila is not None


def entregar_pendientes(
    webhook_url: str,
    limite: int = 20,
    *,
    respetar_pausa: bool = True,
    database_url: str | None = None,
) -> dict[str, int]:
    """Manda los avisos pendientes cuyo plazo ya vencio, del mas viejo al mas nuevo.
    Corta en el primer fallo (el siguiente casi seguro fallaria igual)."""
    global _pausa_hasta
    resultado = {"enviadas": 0, "fallidas": 0}
    if respetar_pausa and time.monotonic() < _pausa_hasta:
        return resultado
    for _ in range(limite):
        with psycopg.connect(_url(database_url)) as conn, conn.transaction():
            fila = conn.execute(
                "SELECT id, incidente_id, texto, intentos FROM aiops_notificaciones "
                "WHERE estado = 'pendiente' AND proximo_intento <= now() "
                "ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED"
            ).fetchone()
            if fila is None:
                return resultado
            nid, incidente_id, texto, intentos = fila
            try:
                gchat.enviar(webhook_url, texto, hilo=incidente_id)
            except gchat.ErrorGChat as exc:
                intentos += 1
                agotada = intentos >= MAX_INTENTOS
                espera = min(_ESPERA_BASE_S * 2 ** (intentos - 1), _ESPERA_MAX_S)
                conn.execute(
                    "UPDATE aiops_notificaciones SET intentos = %s, ultimo_error = %s, "
                    "estado = %s, proximo_intento = now() + make_interval(secs => %s) "
                    "WHERE id = %s",
                    (intentos, str(exc)[:300], "fallida" if agotada else "pendiente", espera, nid),
                )
                resultado["fallidas"] += 1
                _pausa_hasta = time.monotonic() + PAUSA_S
                logger.warning("notificacion %s no entregada (%s): %s", nid, intentos, exc)
                return resultado
            conn.execute(
                "UPDATE aiops_notificaciones SET estado = 'enviada', enviada_en = now(), "
                "intentos = %s, ultimo_error = NULL WHERE id = %s",
                (intentos + 1, nid),
            )
            resultado["enviadas"] += 1
    return resultado


def conteos(database_url: str | None = None) -> dict[str, Any]:
    with psycopg.connect(_url(database_url), autocommit=True) as conn:
        filas = conn.execute(
            "SELECT estado, count(*) FROM aiops_notificaciones GROUP BY estado"
        ).fetchall()
    cuenta = {"pendiente": 0, "enviada": 0, "fallida": 0}
    cuenta.update({estado: int(n) for estado, n in filas})
    return cuenta


def reiniciar_pausa() -> None:
    """Solo para tests."""
    global _pausa_hasta
    _pausa_hasta = 0.0
