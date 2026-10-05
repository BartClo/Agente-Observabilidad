"""Cliente Redis generico. Ver infra/README.md."""

from __future__ import annotations

import os

import redis

_client: redis.Redis | None = None


def get_redis() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.Redis.from_url(os.environ["REDIS_URL"])
    return _client
