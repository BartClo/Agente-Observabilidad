# agent-toolkit (`fw-agents`)

Plantilla delgada sobre [LangChain Deep Agents](https://pypi.org/project/deepagents/)
para crear agentes de dominio **por carpeta**. Un orquestador delega cada pedido al
subagente que mejor calce; agregar un agente nuevo es copiar una carpeta, sin tocar
el código del framework.

## Idea central

- **El LLM no calcula, elige tools.** La lógica de negocio vive en `domain/`, en
  Python puro y testeable. Las tools de cada agente solo formatean entrada/salida.
- **Un agente = una carpeta** en `agents/` con `agent.yaml`, `prompt.md`, `tools.py`,
  `skills/` y `evals/`.
- **Acciones con efecto pasan por aprobación humana** (`require_approval` en `agent.yaml`).
- **Infra opcional y genérica**: Redis, Qdrant, S3 (Garage), Langfuse, Traefik se
  activan por profiles de Docker Compose.

## Estructura

```
app/        Punto de entrada (main.py) y loader que descubre agentes
agents/     Un agente por carpeta (_template/ para copiar, cotizador/ de ejemplo,
            aiops/ agente de incidentes L1)
domain/     Lógica de negocio pura, sin imports de LangChain/deepagents
rag/        Retrieval genérico: chunking, embeddings OpenAI, pgvector
infra/      Clientes de Redis, Qdrant, MCP, cola RQ y object store S3
docker/     Dockerfiles y configs de Garage, Postgres y Traefik
docs/       Documentación (ver abajo)
tests/      Tests del framework (loader, aislamiento de imports)
```

## Inicio rápido

Todo corre dentro de contenedores (`uv` solo existe ahí).

```bash
cp .env.example .env      # completar ANTHROPIC_API_KEY (y OPENAI_API_KEY si usás rag/)
make build
make check                # lint + tipos + tests + cobertura de domain/
make run                  # levanta app + postgres
```

Comandos útiles: `make shell`, `make test`, `make evals`, `make lock`, `make down`.
Ver `Makefile` para la lista completa (incluye `rag-*`).

## Crear un agente

```bash
cp -r agents/_template agents/mi-agente
# editar agent.yaml, prompt.md, tools.py; poner la lógica en domain/
```

`app/loader.py` lo descubre en el próximo arranque. Guía completa en
[`docs/creating-an-agent.md`](docs/creating-an-agent.md).

## Documentación

| Documento | Contenido |
|---|---|
| [`docs/getting-started.md`](docs/getting-started.md) | Instalación, variables de entorno, comandos |
| [`docs/architecture.md`](docs/architecture.md) | Componentes, flujo de un pedido, reglas del framework |
| [`docs/creating-an-agent.md`](docs/creating-an-agent.md) | Cómo crear y probar un agente |
| [`docs/aiops-agent.md`](docs/aiops-agent.md) | Agente AIOps para incidentes L1 (tesis) |
| [`docs/plan-aiops.md`](docs/plan-aiops.md) | Plan por fases, decisiones y estado verificado |
| [`docs/runbook-operacion.md`](docs/runbook-operacion.md) | Operar el agente: kill switch, aprobaciones, rotación de credenciales, fallas |
| [`k8s-lab/README.md`](k8s-lab/README.md) | Laboratorio k3d y cómo correr el ciclo contra él |
| [`docs/open-questions.md`](docs/open-questions.md) | Cosas sin verificar contra fuente oficial |
| [`rag/README.md`](rag/README.md), [`infra/README.md`](infra/README.md), [`domain/README.md`](domain/README.md) | Detalle por componente |

## Stack

Python 3.12 · deepagents 0.7.19 · Postgres + pgvector · Docker Compose · ruff · mypy (strict) · pytest.

## Estado

El agente `aiops` (tesis) tiene implementadas y probadas las fases 0 a 6 de
`docs/plan-aiops.md`: API HTTP (`app/api.py`), persistencia en Postgres, laboratorio
de observabilidad real, acciones sobre Kubernetes y UI embebida en Grafana. Falta
probarlo con el LLM real y la evaluación de la tesis (Fase 7). El agente `cotizador`
es un ejemplo con valores `PLACEHOLDER`, no un producto real.
