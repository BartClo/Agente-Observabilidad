# infra/

Clientes de conexion a componentes de infraestructura que un agente puede
necesitar. A diferencia de `domain/` y `rag/`, este paquete SI puede importar
librerias de LangChain/MCP: su trabajo es justamente entregar tools/clientes
ya compatibles con el framework. No decide que hace un agente con ellos, ni
contiene logica de negocio — eso va en `agents/<agente>/tools.py` o `domain/`.

## `redis_client.py`

`get_redis()` — cliente Redis generico (`REDIS_URL`). Ningun agente lo usa
todavia; esta para cache, rate-limit o sesion corta cuando alguno lo necesite.
Servicio opcional en `docker-compose.yml` (`COMPOSE_PROFILES=redis`).

## `qdrant_client.py`

`get_qdrant_client()` — cliente Qdrant generico (`QDRANT_URL`). Alternativa a
pgvector (`rag/`) para quien necesite un vector store dedicado con mas
features/escala. Ningun agente lo usa todavia. Servicio opcional en
`docker-compose.yml` (`COMPOSE_PROFILES=qdrant`).

## `mcp.py`

Conecta un agente a servidores MCP externos via `langchain-mcp-adapters`. En
`agent.yaml`:

```yaml
mcp_servers:
  nombre_del_servidor:
    transport: stdio        # o "streamable_http" / "sse"
    command: python          # solo stdio
    args: ["/ruta/al/server.py"]
    # url: "http://host:puerto/mcp"   # solo http/sse
```

`app/loader.py` detecta el bloque y agrega las tools del servidor al
subagente, igual que con `rag:`. No hay ningun servidor MCP incluido en este
repo: cada agente apunta al suyo (proceso externo o URL).

## `queue.py`

`get_queue(name="default")` — cola RQ generica sobre Redis. No define que
trabajos existen: eso lo decide quien encola
(`get_queue().enqueue(alguna_funcion, ...)`). El worker que los ejecuta es el
servicio `worker` en `docker-compose.yml` (mismo profile `redis`:
`COMPOSE_PROFILES=redis` levanta redis + worker juntos).

## `object_store.py`

`get_object_store()` — cliente S3-compatible generico (`boto3`), sirve igual
para Garage en dev que para S3 real en prod (en prod simplemente no se pasa
`S3_ENDPOINT_URL`). Ningun agente lo usa todavia. Servicio opcional en
`docker-compose.yml` (`COMPOSE_PROFILES=garage`, imagen `dxflrs/garage`).
Se eligio Garage (Apache-2.0) en vez de MinIO porque la imagen oficial de
MinIO dejo de ser publica en 2025-10-15 (relicenciamiento AGPL) — ver
`docs/open-questions.md`.

## Servicios sin cliente Python: `traefik`

`docker-compose.yml` incluye un `traefik` opcional (`COMPOSE_PROFILES=traefik`)
como reverse proxy hacia `app`. Hoy no hace nada util: `app/main.py` todavia no
expone HTTP (llega con el endpoint FastAPI). Usa el provider "file" de Traefik
(`docker/traefik/`), no el provider "docker" — ese ultimo necesita montar
`docker.sock`, que este repo evita en cualquier servicio.
