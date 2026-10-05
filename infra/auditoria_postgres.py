"""Sink de Postgres para `domain.aiops_core.auditoria.Auditoria` (`on_evento`). Append
only, igual que el JSONL: nunca actualiza ni borra filas. Tabla `aiops_eventos_auditoria`
creada por migrations/versions/9906268772d6_... (`make migrate`).
"""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import UTC, datetime

import psycopg
from psycopg.types.json import Jsonb

from domain.aiops_core.auditoria import Evento


def crear_sink_postgres(database_url: str | None = None) -> Callable[[Evento], None]:
    """Devuelve el callback para `Auditoria(on_evento=...)`. Una conexion nueva por
    evento (mismo criterio que infra/incidentes_postgres.py: sin pool en esta capa)."""
    url = database_url or os.environ["DATABASE_URL"]

    def _sink(evento: Evento) -> None:
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute(
                "INSERT INTO aiops_eventos_auditoria (ts, incidente_id, tipo, datos) "
                "VALUES (%s, %s, %s, %s)",
                (
                    datetime.fromtimestamp(evento.ts, tz=UTC),
                    evento.incidente_id,
                    evento.tipo,
                    Jsonb(evento.datos),
                ),
            )

    return _sink


def eventos_de_incidente(incidente_id: str, database_url: str | None = None) -> list[Evento]:
    """Lee la linea de tiempo de auditoria de un incidente desde Postgres (para la API
    de la Fase 2: `GET /incidentes/{id}`). No reemplaza `Auditoria.de_incidente()`
    dentro del mismo proceso, que sigue leyendo de memoria."""
    url = database_url or os.environ["DATABASE_URL"]
    with psycopg.connect(url, autocommit=True) as conn:
        filas = conn.execute(
            "SELECT ts, incidente_id, tipo, datos FROM aiops_eventos_auditoria "
            "WHERE incidente_id = %s ORDER BY ts",
            (incidente_id,),
        ).fetchall()
    return [Evento(ts.timestamp(), inc_id, tipo, datos) for ts, inc_id, tipo, datos in filas]
