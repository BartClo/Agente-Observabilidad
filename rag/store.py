"""Almacen vectorial sobre pgvector, en el mismo Postgres que el resto. El esquema lo crea
la migracion e5f0b4c8d3a6 (Alembic), no este modulo.

Los vectores estan normalizados (rag.embeddings), asi que `1 - (a <=> b)` es la similitud
coseno. Los filtros (servicio, obsoleto, origen, tipo) los arma quien llama, nunca el LLM.
"""

from __future__ import annotations

import os

import psycopg
from pgvector.psycopg import register_vector

from rag.types import Documento, Fragmento, Pasaje


def get_connection() -> psycopg.Connection:
    conn = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True)
    register_vector(conn)
    return conn


def existe_sha(sha256: str) -> int | None:
    with get_connection() as conn:
        fila = conn.execute("SELECT id FROM rag_documentos WHERE sha256 = %s", (sha256,)).fetchone()
    return int(fila[0]) if fila else None


def guardar_documento(
    doc: Documento, fragmentos: list[Fragmento], vectores: list[list[float]]
) -> int:
    """Idempotente por sha256: el mismo contenido no se duplica. Devuelve el id del documento."""
    if len(fragmentos) != len(vectores):
        raise ValueError("fragmentos y vectores deben tener el mismo largo")
    previo = existe_sha(doc.sha256)
    if previo is not None:
        return previo
    with get_connection() as conn, conn.transaction():
        fila = conn.execute(
            "INSERT INTO rag_documentos (nombre, origen, servicios, tipo, vigente_desde, "
            "obsoleto, sha256, paginas, bytes, subido_por) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (
                doc.nombre,
                doc.origen,
                list(doc.servicios),
                doc.tipo,
                doc.vigente_desde,
                doc.obsoleto,
                doc.sha256,
                doc.paginas,
                doc.bytes_,
                doc.subido_por,
            ),
        ).fetchone()
        assert fila is not None
        doc_id = int(fila[0])
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO rag_chunks (documento_id, pagina, orden, content, embedding) "
                "VALUES (%s, %s, %s, %s, %s)",
                [
                    (doc_id, f.pagina, f.orden, f.contenido, v)
                    for f, v in zip(fragmentos, vectores, strict=True)
                ],
            )
    return doc_id


def buscar(
    vector: list[float],
    *,
    servicio: str | None,
    k: int,
    min_sim: float,
    origenes: tuple[str, ...],
    excluir_tipos: tuple[str, ...] = (),
) -> list[Pasaje]:
    """`servicio=None` no filtra por servicio (chat); con servicio, documentos de ese servicio
    mas los generales. Nunca devuelve obsoletos."""
    sql = (
        "SELECT c.id, d.nombre, c.pagina, c.content, "
        "1 - (c.embedding <=> %(q)s::vector) AS sim, d.vigente_desde "
        "FROM rag_chunks c JOIN rag_documentos d ON d.id = c.documento_id "
        "WHERE NOT d.obsoleto AND d.origen = ANY(%(origenes)s) "
        "AND NOT (d.tipo = ANY(%(excl)s)) "
        "AND (%(srv)s::text IS NULL OR cardinality(d.servicios) = 0 "
        "OR %(srv)s::text = ANY(d.servicios)) "
        "AND 1 - (c.embedding <=> %(q)s::vector) >= %(min)s "
        "ORDER BY c.embedding <=> %(q)s::vector LIMIT %(k)s"
    )
    params = {
        "q": vector,
        "origenes": list(origenes),
        "excl": list(excluir_tipos),
        "srv": servicio,
        "min": min_sim,
        "k": k,
    }
    with get_connection() as conn:
        filas = conn.execute(sql, params).fetchall()
    return [Pasaje(int(r[0]), r[1], r[2], r[3], float(r[4]), r[5]) for r in filas]


def listar_documentos() -> list[dict[str, object]]:
    cols = ("id", "nombre", "origen", "servicios", "tipo", "obsoleto", "paginas", "bytes")
    with get_connection() as conn:
        filas = conn.execute(f"SELECT {', '.join(cols)} FROM rag_documentos ORDER BY id").fetchall()
    return [dict(zip(cols, f, strict=True)) for f in filas]


def borrar_documento(documento_id: int) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM rag_documentos WHERE id = %s", (documento_id,))
