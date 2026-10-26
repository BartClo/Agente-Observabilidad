# rag/ — base de conocimiento

Python puro + Postgres/pgvector + embeddings de Gemini (`gemini-embedding-001`, 1536
dimensiones). Diseño: `docs/superpowers/specs/2026-10-25-rag-conocimiento-design.md`.

El RAG **informa, no autoriza**: lo usa el agente de incidentes
(`agents/aiops/conocimiento.py`, filtrado por el servicio del incidente y con citas
verificadas por el dominio) y el chat de consulta.

## Uso

La key de Gemini se carga cifrada desde la UI (proveedor Google), no en `.env`.

```bash
make rag-indexar RUTA=corpus          # .md y .pdf; metadatos en el encabezado del .md
make rag-listar
make aiops-ingest                     # runbooks (tipo runbook) + corpus
```

Encabezado de un `.md`:

```
---
servicios: checkout, api     # vacio = general
tipo: postmortem             # ficha | arquitectura | postmortem | guia | runbook | otro
vigente_desde: 2026-08-01
obsoleto: false
---
```

## Piezas

- `embeddings.py`: único archivo que conoce al proveedor (Gemini). Lotes de 100, 3
  intentos, vectores normalizados; los errores nunca incluyen la key.
- `ingest.py`: lee Markdown y PDF (máx. 5 MB, 200 páginas), enmascara secretos antes de
  embeber y es idempotente por `sha256`.
- `chunking.py`: fragmentos con solapamiento; nunca cruzan de página.
- `store.py`: documentos y fragmentos (esquema en la migración `e5f0b4c8d3a6`); búsqueda
  coseno con filtros por servicio, obsoleto, origen y tipo, y piso de similitud.
- `retrieve.py`: adaptador del loader genérico (`rag:` en `agent.yaml`), sin filtro de servicio.

Configuración: `AIOPS_RAG` (1), `AIOPS_RAG_K` (4), `AIOPS_RAG_MIN_SIM` (0 hasta calibrar),
`AIOPS_RAG_ORIGENES` (`repo,subido`), `AIOPS_EMBEDDING_MODEL`, `AIOPS_EMBEDDING_DIM`.
