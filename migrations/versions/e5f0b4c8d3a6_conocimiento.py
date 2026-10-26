"""base de conocimiento (RAG): documentos y fragmentos con metadatos

Revision ID: e5f0b4c8d3a6
Revises: d4e9a3b7c2f5
Create Date: 2026-10-25

Reemplaza la tabla rag_chunks que creaba rag.store.init_db (sin Alembic y sin metadatos):
ahora cada fragmento pertenece a un documento con servicios, tipo, vigencia y origen, que
es lo que permite filtrar por el servicio del incidente. Vectores de 1536 dimensiones
(gemini-embedding-001). Con un corpus de cientos de fragmentos la busqueda exacta alcanza:
no se crea indice aproximado.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e5f0b4c8d3a6"
down_revision: str | Sequence[str] | None = "d4e9a3b7c2f5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS rag_documentos (
            id BIGSERIAL PRIMARY KEY,
            nombre TEXT NOT NULL,
            origen TEXT NOT NULL,
            servicios TEXT[] NOT NULL DEFAULT '{}',
            tipo TEXT NOT NULL,
            vigente_desde DATE,
            obsoleto BOOLEAN NOT NULL DEFAULT false,
            sha256 TEXT NOT NULL UNIQUE,
            paginas INT,
            bytes INT,
            subido_por TEXT,
            subido_en TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("DROP TABLE IF EXISTS rag_chunks")  # la anterior no tenia datos ni se usaba
    op.execute(
        """
        CREATE TABLE rag_chunks (
            id BIGSERIAL PRIMARY KEY,
            documento_id BIGINT NOT NULL REFERENCES rag_documentos(id) ON DELETE CASCADE,
            pagina INT,
            orden INT NOT NULL,
            content TEXT NOT NULL,
            embedding VECTOR(1536) NOT NULL
        )
        """
    )
    op.execute("CREATE INDEX rag_chunks_doc_idx ON rag_chunks (documento_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS rag_chunks")
    op.execute("DROP TABLE IF EXISTS rag_documentos")
