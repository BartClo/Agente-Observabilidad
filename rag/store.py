"""Almacen vectorial sobre pgvector, en el mismo Postgres que usa el checkpointer.

Namespacing: cada fila lleva `collection` + `tenant_id`. Hoy el aislamiento fuerte
entre tenants lo decide quien ingiere (usar una `collection` por tenant, ej.
"parafiscal__acme"); la columna `tenant_id` queda para filtrar ademas por ese
campo el dia que el `collection` se comparta entre tenants. Ver docs/open-questions.md.
"""

from __future__ import annotations

import os

import psycopg
from pgvector.psycopg import register_vector

from rag.embeddings import EMBEDDING_DIM
from rag.types import Chunk, SearchResult


def get_connection() -> psycopg.Connection:
    conn = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True)
    conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    register_vector(conn)
    return conn


def init_db() -> None:
    with get_connection() as conn:
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS rag_chunks (
                id BIGSERIAL PRIMARY KEY,
                collection TEXT NOT NULL,
                tenant_id TEXT NOT NULL DEFAULT 'default',
                source TEXT NOT NULL,
                content TEXT NOT NULL,
                embedding VECTOR({EMBEDDING_DIM}) NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS rag_chunks_collection_idx "
            "ON rag_chunks (collection, tenant_id)"
        )


def upsert_chunks(
    collection: str, tenant_id: str, chunks: list[Chunk], embeddings: list[list[float]]
) -> int:
    if len(chunks) != len(embeddings):
        raise ValueError("chunks y embeddings deben tener el mismo largo")
    with get_connection() as conn, conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO rag_chunks (collection, tenant_id, source, content, embedding) "
            "VALUES (%s, %s, %s, %s, %s)",
            [
                (collection, tenant_id, c.source, c.content, e)
                for c, e in zip(chunks, embeddings, strict=True)
            ],
        )
    return len(chunks)


def search(
    collection: str, query_embedding: list[float], k: int, tenant_id: str | None = None
) -> list[SearchResult]:
    sql = (
        "SELECT content, source, embedding <-> %(query)s::vector AS distance "
        "FROM rag_chunks WHERE collection = %(collection)s "
    )
    params: dict[str, object] = {
        "query": query_embedding,
        "collection": collection,
        "k": k,
    }
    if tenant_id is not None:
        sql += "AND tenant_id = %(tenant_id)s "
        params["tenant_id"] = tenant_id
    sql += "ORDER BY distance ASC LIMIT %(k)s"

    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [SearchResult(content=r[0], source=r[1], distance=r[2]) for r in rows]
