# Arquitectura

## Flujo de un pedido

1. `app/main.py` arma un Deep Agent orquestador (`create_deep_agent`).
2. `app/loader.py` recorre `agents/*/agent.yaml` (ignora carpetas que empiezan con `_`)
   y convierte cada una en un `SubAgent`.
3. El orquestador no resuelve nada: delega al subagente cuyo `description` calce mejor.
   Si ninguno calza, lo dice.
4. El subagente llama tools (`agents/<x>/tools.py`), que delegan en `domain/`.
5. Tools listadas en `require_approval` quedan pausadas (`interrupt_on`) hasta
   aprobación humana.

## Qué arma el loader desde `agent.yaml`

| Campo | Resultado |
|---|---|
| `name`, `description`, `model` | Identidad y modelo del subagente |
| `prompt` | Contenido de ese archivo como system prompt |
| `tools` | Referencias `modulo:funcion` cargadas desde la carpeta del agente |
| `skills` | Subcarpetas con `SKILL.md` |
| `require_approval` | `interrupt_on` para esas tools |
| `rag` (opcional) | Tool `buscar_documentos` sobre una `collection` |
| `mcp_servers` (opcional) | Tools de servidores MCP externos |

## Capas y reglas

- `domain/`: lógica de negocio pura. Sin imports de deepagents/LangChain/LangGraph
  (lo verifica `tests/test_no_framework_imports.py`). Cobertura >= 90%.
- `rag/`: igual restricción de imports. Postgres/pgvector + embeddings OpenAI.
  Proveedor de embeddings aislado en `rag/embeddings.py`.
- `infra/`: sí puede importar LangChain/MCP. Sin lógica de negocio.
- `agents/`: solo pegamento. El LLM elige tools; no calcula.
- Efectos reales requieren aprobación humana.
- `docker.sock` no se monta en ningún servicio. El código del agente QA solo corre
  en el servicio `sandbox` (sin red).

## Servicios de Compose

`app`, `postgres` (imagen pgvector) siempre. Opcionales por profile: `sandbox`,
`redis` + `worker`, `qdrant`, `garage`, `langfuse`, `traefik`.

## Multi-tenant (RAG)

Aislamiento por `collection` (una por tenant). La columna `tenant_id` existe pero
falta conectarla al endpoint HTTP. Ver `rag/README.md`.
