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
| `AIOPS_EMBEDDING_MODEL` (opcional) | Modelo de embeddings de `rag/` (Gemini; la key va cifrada desde la UI) |
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

## Conectar Jira

Jira Cloud puede ser una fuente de incidentes: el agente sondea la columna de entrada de un
tablero y cada ticket nuevo entra como alerta (ver D22).

1. Crear un API token en `id.atlassian.com/manage-profile/security/api-tokens`.
2. Abrir la UI del agente e ingresar el token admin en la parte superior.
3. En la sección Jira, cargar el sitio (`https://<empresa>.atlassian.net`), el correo y el API token. Pulsar **Guardar conexión**.
4. Pulsar **Probar conexión**.
5. Pulsar **Cargar tableros** y elegir el tablero.
6. Elegir la columna de **Entrada**, la de resuelto y la de escalado. Ajustar **Cada** (segundos) y pulsar **Guardar tablero**.
7. Pulsar **Activar escucha**. Para pausarla, pulsar **Pausar escucha**.

Etiquetas recomendadas en cada ticket: `servicio:<nombre>` y `categoria:<id>` (por ejemplo
`servicio:api` y `categoria:pod_fallido`). Sin ellas, el agente clasifica con el LLM.
