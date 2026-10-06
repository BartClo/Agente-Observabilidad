"""Aisla los tests de la base y la cola del laboratorio (Fase 6).

Los tests de integracion limpian sus tablas al terminar (`DELETE FROM aiops_*`). Antes
corrian contra la MISMA base que el laboratorio (DATABASE_URL), asi que `make test` con
el laboratorio levantado borraba los incidentes reales. Ahora apuntan a una base aparte
(`<base>_test`, o TEST_DATABASE_URL si se define), que se crea y migra sola.

Se ejecuta antes de importar cualquier test: todo el codigo lee DATABASE_URL en el
momento de usarlo, asi que reemplazar la variable aca alcanza.
"""

from __future__ import annotations

import os
import urllib.parse


def _url_de_tests(url: str) -> str:
    partes = urllib.parse.urlsplit(url)
    base = partes.path.lstrip("/") or "postgres"
    return urllib.parse.urlunsplit(partes._replace(path=f"/{base}_test"))


def _preparar_base_de_tests() -> None:
    original = os.environ.get("DATABASE_URL")
    if not original:
        return  # sin Postgres (p. ej. corriendo solo domain/ fuera del contenedor)
    destino = os.environ.get("TEST_DATABASE_URL") or _url_de_tests(original)
    if destino == original:
        raise RuntimeError("La base de tests no puede ser la misma que DATABASE_URL")

    import psycopg

    nombre = urllib.parse.urlsplit(destino).path.lstrip("/")
    with psycopg.connect(original, autocommit=True) as conn:
        existe = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (nombre,)).fetchone()
        if not existe:
            conn.execute(f'CREATE DATABASE "{nombre}"')

    os.environ["DATABASE_URL"] = destino

    from alembic import command
    from alembic.config import Config

    command.upgrade(Config(os.path.join(os.path.dirname(__file__), "alembic.ini")), "head")


def _aislar_redis() -> None:
    """Mismo problema que con Postgres: tests/test_api_webhook.py vacia la cola `aiops`
    al terminar, y era la misma cola del laboratorio. Los tests usan otra base logica de
    Redis (la /15, o TEST_REDIS_URL)."""
    original = os.environ.get("REDIS_URL")
    if not original:
        return
    destino = os.environ.get("TEST_REDIS_URL") or urllib.parse.urlunsplit(
        urllib.parse.urlsplit(original)._replace(path="/15")
    )
    if destino == original:
        raise RuntimeError("La base de Redis de tests no puede ser la misma que REDIS_URL")
    os.environ["REDIS_URL"] = destino


_preparar_base_de_tests()
_aislar_redis()
