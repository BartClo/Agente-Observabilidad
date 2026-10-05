# TODO(verificar)

Cosas que no se pudieron confirmar contra documentacion/fuente oficial al momento
de escribirlas. Revisar antes de depender de ellas en produccion.

## Etapa 1

- **Nombres exactos de clases de backend de filesystem de `deepagents`** (p. ej.
  si existe `FilesystemBackend`/`StateBackend`/`CompositeBackend` con esos nombres
  literales). La doc de overview describe el concepto pero no lista las clases.
  Confirmar en `reference.langchain.com/python/deepagents/backends` dentro del
  contenedor (`make shell` -> `python -c "import deepagents; help(deepagents)"`)
  antes de usar un backend distinto del default en `create_deep_agent`.

- ~~Version exacta de `langgraph-checkpoint-postgres`~~ **RESUELTO (2026-10-05)**:
  confirmado por fetch directo a `https://pypi.org/pypi/langgraph-checkpoint-postgres/json`,
  no por busqueda web. Latest es `3.1.2` (2026-08-07), exige
  `langgraph-checkpoint>=4.1.0,<5.0.0`. `deepagents==0.7.19` no la fija de forma
  directa (la trae transitiva via `langchain`/`langgraph`), asi que el pin final
  lo termina de confirmar `uv add langgraph-checkpoint-postgres==3.1.2` dentro del
  contenedor cuando se implemente la Fase 1 de `docs/plan-aiops.md` (dejar que
  `uv.lock` resuelva las transitivas, no adivinarlas).

- **Formato esperado de `SubAgent["skills"]`**: `app/loader.py` (`_load_skills`)
  asume que es una lista de rutas de carpeta (una por skill, cada una con
  `SKILL.md` adentro). No confirmado contra la firma exacta de `SubAgent` en
  `deepagents/middleware/subagents.py` mas alla del nombre del campo. Verificar
  cuando se agregue la primera skill real no trivial.

- **Receta self-host de Langfuse solo con Postgres** (`docker-compose.yml`,
  servicio `langfuse`, imagen `langfuse/langfuse:2`). No confirmada contra la
  guia oficial de self-hosting actual; Langfuse v3 pide Clickhouse/Redis/MinIO
  ademas de Postgres. Revisar antes de activar el profile `langfuse` en serio.

## Infra (MCP / Redis / Qdrant)

- **`langchain-mcp-adapters` podria estar migrando a `langchain[mcp]`**
  (namespace `langchain.mcp`). Visto solo en un snippet de busqueda (conda-forge),
  no confirmado por fetch directo. `infra/mcp.py` pinea `langchain-mcp-adapters==0.3.2`;
  revisar el aviso de migracion antes de actualizar esa dependencia mas adelante.

- **Snippet oficial exacto de deepagents integrando tools de MCP**: confirmado el
  patron (`MultiServerMCPClient().get_tools()` -> lista pasada a `tools=` de
  `create_deep_agent`, y que Deep Agents soporta MCP oficialmente), pero no se
  pudo copiar codigo literal del README de deepagents. `infra/mcp.py` sigue el
  patron descrito en `docs.langchain.com/oss/python/deepagents/overview`, no un
  ejemplo copiado. Probar contra un servidor MCP real antes de confiar en el.

- **Pin de imagen `qdrant/qdrant:v1.19.1`** en `docker-compose.yml`: elegido para
  alinear protocolo con `qdrant-client>=1.19,<2.0` en `pyproject.toml`. Si se
  actualiza uno, actualizar el otro en el mismo cambio.

## Agente aiops

- **Esquema de tools desde funciones envueltas**: `agents/aiops/tools.py` envuelve
  cada tool con `functools.wraps` (devuelve los errores como texto). Se asume que
  LangChain arma el esquema siguiendo `__wrapped__` (firma y docstring originales).
  PARCIAL (2026-10-05): `tests/test_loader_aiops.py` corre dentro del contenedor
  con `deepagents` instalado y pasa: el loader resuelve y carga las 14 tools sin
  error. Sigue sin confirmar que el LLM reciba el esquema correcto en una llamada
  real: falta `make aiops-demo` con `ANTHROPIC_API_KEY` (no disponible en esta
  sesion) antes de confiar en ello para produccion.

- **Consultas PromQL/LogQL de `infra/observabilidad.py`**: supuestos sobre
  node_exporter, kube-state-metrics, rabbitmq y blackbox_exporter, y la etiqueta
  `service`. Ajustarlos a las metricas reales del entorno de la tesis.

- **Tool con aprobacion (nivel 2) de punta a punta**: `interrupt_on` pausa el grafo,
  pero reanudarlo necesita checkpointer y un canal humano (endpoint/UI). `make
  aiops-demo` usa el nivel 3 para no depender de eso.

- **Catalogo L1 y runbooks**: los valores son candidatos de diseño de la tesis
  (`PLACEHOLDER` en vigencia/propietario). Validar con operaciones.

## Infra (Garage / worker / Traefik)

- **MinIO oficial descartado, se uso Garage en su lugar**: la imagen
  `minio/minio` dejo de publicarse gratis en Docker Hub/quay.io desde
  2025-10-15 (licencia AGPL, ahora solo-fuente o con suscripcion). En vez de
  usar un archivo legacy sin actualizaciones (`bitnamilegacy/minio`, que se
  probo primero), se cambio a Garage (Apache-2.0, activamente mantenido,
  `dxflrs/garage:v2.3.0`), confirmado con pull real + `--help` de sus flags.

- **`garage.toml` con secretos placeholder fijos** (`rpc_secret`, `admin_token`,
  `metrics_token`): validos para un nodo unico local, no para exponer a una red
  que no sea localhost. Regenerar con `openssl rand` antes de eso.

- **Layout multi-nodo de Garage no cubierto**: `--single-node --default-bucket`
  solo sirve para un nodo de dev. Si algun agente futuro necesita Garage en
  cluster real, revisar `garage layout assign/apply` (bootstrap manual, distinto
  del modo single-node).

- **`rq` como cola de trabajos**: eleccion razonable (liviana, sobre Redis que ya
  esta), pero no se comparo contra alternativas (Celery, Arq) contra los
  requisitos reales de ningun agente todavia, porque ningun agente la usa. Si un
  agente futuro necesita reintentos complejos/scheduling, revisar si `rq` alcanza.
