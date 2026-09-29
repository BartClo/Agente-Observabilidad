"""Cliente Qdrant generico. Ver infra/README.md."""

from __future__ import annotations

import os

from qdrant_client import QdrantClient

_client: QdrantClient | None = None


def get_qdrant_client() -> QdrantClient:
    global _client
    if _client is None:
        _client = QdrantClient(url=os.environ["QDRANT_URL"])
    return _client
