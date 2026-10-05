# rag/

Componente de retrieval generico (no es especifico de ningun agente). Vive al
mismo nivel que `domain/`: Python puro + Postgres/pgvector + OpenAI embeddings,
sin imports de deepagents/LangChain/LangGraph (un test lo verifica, igual que
en `domain/`).

## Probarlo por terminal, sin agente

```bash
cp .env.example .env   # completar OPENAI_API_KEY
make rag-init-db
make rag-ingest COLLECTION=demo SRC=agents/_template/skills
make rag-query COLLECTION=demo Q="que es esta skill?"
```

`make rag-query` imprime cada resultado con su `fuente` y distancia — es la
forma de ver que esta indexado antes de cablearlo a un agente.

## Cablearlo a un agente

En `agents/<tu-agente>/agent.yaml` agregar:

```yaml
rag:
  collection: mi_coleccion   # la que usaste en `make rag-ingest`
  k: 4                        # opcional, default 4
```

`app/loader.py` detecta ese bloque y agrega sola una tool `buscar_documentos`
al subagente — no hace falta escribir nada en `tools.py`. La tool devuelve
`content` + `source` de cada resultado, para que el agente cite la fuente
(ver regla 10 del framework: respuestas legales/fiscales necesitan fuente y
aprobacion humana antes de salir al cliente).

## Multi-tenant

El aislamiento entre tenants hoy se resuelve con la `collection`: si dos
tenants no deben compartir contenido, usar una `collection` por tenant al
ingerir (ej. `parafiscal__acme`, `parafiscal__beta`), no la misma collection
con distinto `tenant_id`. La columna `tenant_id` en `rag_chunks` existe para
filtrar ademas por ese campo cuando haga falta compartir `collection` entre
tenants; conectar eso al `tenant_id` real de la request es trabajo de la etapa
4 (endpoint), no esta resuelto todavia. Ver `docs/open-questions.md`.

## Si hay que cambiar de proveedor de embeddings

Tocar solo `rag/embeddings.py`. `store.py`, `ingest.py` y `retrieve.py` no
saben que el proveedor es OpenAI.
