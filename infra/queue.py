"""Cola de trabajos generica sobre RQ/Redis. No define que trabajos existen:
eso lo decide quien encola (`get_queue().enqueue(alguna_funcion, ...)`). El
worker que los ejecuta es el servicio `worker` en docker-compose.yml (mismo
profile "redis"). Ver infra/README.md."""

from __future__ import annotations

from rq import Queue

from infra.redis_client import get_redis


def get_queue(name: str = "default") -> Queue:
    return Queue(name, connection=get_redis())
