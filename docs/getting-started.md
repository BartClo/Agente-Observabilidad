# Primeros pasos

## Requisitos

Docker y Docker Compose. Python y `uv` corren dentro del contenedor `app`.

## Setup

```bash
cp .env.example .env
make build
```

Variables principales de `.env`:

| Variable | Uso |
|---|---|
| `ANTHROPIC_API_KEY` | Modelo del orquestador y subagentes |
| `OPENAI_API_KEY`, `RAG_EMBEDDING_MODEL` | Embeddings de `rag/` |
| `DATABASE_URL`, `POSTGRES_*` | Postgres (checkpointer, pgvector) |
| `COMPOSE_PROFILES` | Servicios opcionales: `redis`, `qdrant`, `garage`, `langfuse`, `traefik`, `sandbox` |
| `REDIS_URL`, `QDRANT_URL`, `S3_*` | Conexión a infra opcional |
| `ORCHESTRATOR_MODEL` | Opcional. Default `anthropic:claude-sonnet-5` |

Nunca commitear `.env`.

## Comandos (`make`)

| Comando | Qué hace |
|---|---|
| `build` | Construye imágenes |
| `lock` | Regenera `uv.lock` (tras tocar `pyproject.toml`) |
| `check` | `lint` + `typecheck` + `test` + `coverage` |
| `test` | Tests sin evals |
| `evals` | Solo tests marcados `eval` |
| `coverage` | `domain/` exige >= 90% |
| `run` | Levanta `app` y `postgres` |
| `shell` | Shell en el contenedor |
| `down` | Baja servicios y borra volúmenes |
| `rag-init-db`, `rag-ingest`, `rag-query` | Ver `rag/README.md` |

## Servicios opcionales

Sumar el profile a `COMPOSE_PROFILES` en `.env`, por ejemplo
`COMPOSE_PROFILES=redis,qdrant,garage`. `redis` levanta también el `worker` RQ.
Detalle en `infra/README.md`.
