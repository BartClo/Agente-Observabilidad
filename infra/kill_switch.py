"""Kill switch en Postgres: unica fuente de verdad compartida entre procesos (`api`,
`worker`). Reemplaza la variable de entorno / archivo de `politicas.politica_desde_entorno`,
que no sirve para desactivar un proceso que ya esta corriendo (ver docs/plan-aiops.md
Fase 2). Tabla `aiops_kill_switch` (fila unica) creada por
migrations/versions/9906268772d6_... (`make migrate`), con una fila inicial `activo=false`.
"""

from __future__ import annotations

import os
from collections.abc import Callable

import psycopg


def _conectar(database_url: str | None) -> psycopg.Connection[None]:
    return psycopg.connect(database_url or os.environ["DATABASE_URL"], autocommit=True)


def leer(database_url: str | None = None) -> bool:
    with _conectar(database_url) as conn:
        fila = conn.execute("SELECT activo FROM aiops_kill_switch WHERE id = true").fetchone()
    return bool(fila[0]) if fila else False


def activar(usuario: str, motivo: str, database_url: str | None = None) -> None:
    with _conectar(database_url) as conn:
        conn.execute(
            "UPDATE aiops_kill_switch SET activo = true, usuario = %s, motivo = %s, "
            "actualizado_en = now() WHERE id = true",
            (usuario, motivo),
        )


def desactivar(usuario: str, database_url: str | None = None) -> None:
    with _conectar(database_url) as conn:
        conn.execute(
            "UPDATE aiops_kill_switch SET activo = false, usuario = %s, motivo = NULL, "
            "actualizado_en = now() WHERE id = true",
            (usuario,),
        )


def kill_switch_postgres(database_url: str | None = None) -> Callable[[], bool]:
    """Callable para `Politica(kill_switch=...)`: lee el valor actual en cada llamada
    (la politica se evalua en cada ejecucion, nunca cachea el kill switch)."""

    def _leer() -> bool:
        return leer(database_url)

    return _leer
