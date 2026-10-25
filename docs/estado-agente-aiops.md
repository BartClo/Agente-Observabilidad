# Agente AIOps L1: estado completo y pendientes

> Estado al 2026-10-06 · último commit `65c42be` · 150 tests en verde · mypy estricto sin
> errores · cobertura de `domain/` 99.48 %.
>
> Documentos de detalle: `docs/plan-aiops.md` (plan por fases con decisiones y
> verificaciones), `docs/aiops-agent.md` (diseño), `docs/runbook-operacion.md`
> (operación), `docs/protocolo-experimento.md` (evaluación), `k8s-lab/README.md`
> (laboratorio).

---

## 1. Resumen ejecutivo

El agente detecta incidentes operacionales recurrentes de nivel 1, los confirma con
métricas reales, los clasifica contra un catálogo, decide con una política
determinista si puede actuar, ejecuta la acción autorizada sobre Kubernetes, verifica la
recuperación y cierra, o escala a un humano con la evidencia. Todo queda auditado y
medido (TRA, MTTR, costo en tokens).

**Lo que funciona y está verificado en vivo** contra un laboratorio real (Prometheus,
Grafana, RabbitMQ, k3d), sin mocks:

- Una alerta real de Grafana llega por webhook, se encola y la atiende un worker.
- El ciclo resuelve solo `pod_fallido` y `servicio_detenido` en Kubernetes (9–16 s de
  MTTR en el laboratorio).
- En nivel 2, el ciclo se pausa y un humano aprueba desde una UI embebida en Grafana.
  El clic real lo probó el usuario.

**La brecha principal:** el agente con LLM **nunca corrió**, porque no hay
`ANTHROPIC_API_KEY`. Las corridas de punta a punta usaron `scripts/lab_ciclo.py`, que
recorre el mismo ciclo con un diagnóstico fijo. El código que invoca al LLM está
cableado y probado con un agente falso, pero no se sabe aún cómo se comporta el modelo
real ni cuánto cuesta.

**Avance estimado: ~90 % del plan.** Están completas las fases 0 a 6 y la
infraestructura de la Fase 7. Falta correr el experimento con el LLM y la línea base
manual.

---

## 2. Qué es y qué no es

**Es** un agente único (requisito de la tesis) para el catálogo L1 de 5 categorías,
sobre un laboratorio específico. El detector, la política, el ejecutor y el verificador
son funciones de dominio que el agente usa como tools, no agentes aparte.

**No es** una plataforma AIOps genérica para cualquier proyecto:

- El catálogo está en código (`domain/aiops_core/catalogo.py`).
- Las consultas PromQL asumen nombres de métricas concretos.
- El backend de acciones es Kubernetes.
- No es multi-tenant.

Generalizarlo es otro proyecto.

---

## 3. Arquitectura

```
Grafana (reglas L1) ──webhook──▶ API (FastAPI, app/api.py) ──encola──▶ Redis/RQ
                                    │  /ui  /incidentes  /metricas  /metrics       │
                                    ▼                                              ▼
                               Postgres ◀──────────── Worker (agents/aiops/worker_jobs.py)
                  (incidentes, auditoría,                  │  lock por servicio
                   kill switch, checkpoints)               ▼
                                                 Agente (deepagents + LLM)
                                                   tools ─▶ Ciclo (domain/)
                                                    │            │
                                        Prometheus ◀┘            └▶ Kubernetes (k3d)
                                     (confirmar, verificar)       (recrear pod, reiniciar)
```

### Capas

| Capa | Qué contiene | Regla |
|---|---|---|
| `domain/aiops_core/` | Ciclo del incidente, catálogo, política, métricas, evaluación de la tesis | Python puro, sin LangChain; cobertura ≥ 90 % |
| `infra/` | Adaptadores: Prometheus/Loki, Kubernetes, Postgres, Redis, webhook de Grafana | Sin lógica de negocio |
| `agents/aiops/` | Prompt, tools (pegamento), runtime, worker | El LLM elige tools; no decide si algo es seguro |
| `app/` | API HTTP, UI, orquestador | |
| `scripts/` | Inyección de fallas, ciclo de laboratorio, experimento, análisis | |

**Invariantes de seguridad en código, no en el prompt:**

- La política se evalúa en cada ejecución.
- No se cierra sin verificación.
- Solo se ejecutan acciones de una lista autorizada, con el servicio validado.
- El kill switch bloquea toda ejecución, pero nunca el escalamiento.
- Nunca se monta `docker.sock`.

### Stack tecnológico

| Área | Tecnología | Versión | Uso |
|---|---|---|---|
| Lenguaje | Python | 3.12 (`python:3.12-slim`) | Todo el código |
| Gestor de dependencias | uv | — | `uv.lock` y ejecución en el contenedor |
| Framework del agente | deepagents (sobre LangChain y LangGraph) | 0.7.19 | Orquestador, subagente, tools y skills |
| LLM (multiproveedor) | langchain-anthropic, langchain-openai, langchain-google-genai, langchain-deepseek | openai ≥ 1.1.9 · deepseek ≥ 1.1.0 | Anthropic, OpenAI, Gemini y DeepSeek, elegibles desde la UI |
| Herramientas MCP | langchain-mcp-adapters | 0.3.2 | Tools externas por MCP |
| Checkpointer | langgraph-checkpoint-postgres | 3.1.2 | Instalado; falta cablear la reanudación |
| API HTTP | FastAPI + Uvicorn (+ httpx) | ≥ 0.142 / ≥ 0.54 | Webhook, incidentes, aprobación, configuración |
| UI | HTML + JavaScript vanilla | — | `/ui`, embebida en Grafana por iframe |
| Base de datos | PostgreSQL 16 con pgvector | `pgvector/pgvector:pg16` | Incidentes, auditoría, kill switch, keys cifradas, RAG |
| Acceso a la base y migraciones | psycopg 3 · Alembic | 3.x · 1.20.0 | SQL directo con JSONB y migraciones versionadas |
| Cola de trabajos | Redis + RQ | `redis:7-alpine` · rq 2.x | Webhook → worker, lock por servicio, reintentos |
| Cifrado | cryptography (Fernet) | ≥ 50.0.1 | API keys en reposo |
| RAG de runbooks | Embeddings de OpenAI + pgvector | openai 1.x | La tool `buscar_documentos` |
| Métricas | Prometheus | 3.0.1 | Confirmar y verificar anomalías |
| Alertas y dashboards | Grafana (alertas gestionadas por Grafana) | 11.4.0 | Reglas L1 como código, contact point por webhook, dashboard `aiops-l1` |
| Exporters | node_exporter · blackbox_exporter · kube-state-metrics | 1.8.2 · 0.25.0 · 2.13.0 | Disco, certificado TLS, estado de pods |
| Mensajería (laboratorio) | RabbitMQ | 3.13-management | Escenario `cola_detenida` |
| Kubernetes (laboratorio) | k3d / k3s | 5.9.0 / 1.35.5 | Backend de acciones, con un ServiceAccount de RBAC mínimo |
| Workloads del laboratorio | busybox, nginx | 1.36 · 1.27 | Servicios a romper; certificado de 3 días |
| Contenedores | Docker Compose (profiles) | — | Todo el laboratorio, salvo k3d |
| Opcionales en el compose (no los usa el agente) | Qdrant, Garage (S3), Langfuse, Traefik | — | Heredados de la plantilla |
| Calidad | ruff · mypy (estricto) · pytest + pytest-cov | — | Lint, tipos, tests y cobertura |

---

## 4. El ciclo del incidente

`abrir → confirmar anomalía → clasificar → diagnosticar → ejecutar → verificar → cerrar | escalar | descartar`

| Paso | Qué hace | Dónde |
|---|---|---|
| Abrir | Desde una alerta por pull (`alertas_activas`) o push (webhook). Una alerta recurrente nunca reabre un incidente ya cerrado | `Ciclo.abrir`, `abrir_desde_alerta` |
| Confirmar | Contrasta la alerta con la señal sana de su categoría. Sin datos = sin evidencia → escalar. Reintenta solo mientras no hay datos (`AIOPS_CONFIRM_WINDOW_S`) | `Ciclo.confirmar_anomalia` |
| Clasificar | Categoría L1 y elegibilidad. No elegible si está fuera del catálogo, es solo de detección o tiene severidad crítica | `Ciclo.clasificar` |
| Diagnosticar | Causa, confianza (0–1) y runbook, que debe coincidir con la categoría. Lo aporta el LLM | `registrar_diagnostico` |
| Ejecutar | La política decide: permitir, pedir aprobación o denegar. Solo la acción autorizada de la categoría | `ejecutar_remediacion` |
| Verificar | Vuelve a leer la métrica hasta recuperar o agotar la ventana (`AIOPS_VERIFY_WINDOW_S`) | `Ciclo.verificar` |
| Cerrar | Solo si se verificó la recuperación | `Ciclo.cerrar` |
| Revertir | Rollback, solo en nivel 4 y si el runbook lo define | `Ciclo.revertir` |
| Escalar | Siempre permitido; entrega un paquete con evidencia y acciones | `Ciclo.escalar` |

### Catálogo L1

| Categoría | Alerta | Señal sana | Acción | ¿Remediable en el laboratorio? |
|---|---|---|---|---|
| `servicio_detenido` | ServiceDown | `up ≥ 1` | `restart_service` (rollout restart) | **Sí** (k3d) |
| `pod_fallido` | PodFailed / PodCrashLooping | `pod_ready ≥ 1` | `recreate_pod` | **Sí** (k3d) |
| `disco_lleno` | DiskUsageHigh | `disk_usage_percent ≤ 85` | `compress_old_logs` (rollback: `restore_compressed_logs`) | No: no es una operación de Kubernetes → escala |
| `cola_detenida` | QueueStalled | `queue_consumers_active ≥ 1` | `restart_consumer` | No: sin consumidor en k3d ni métricas por cola → escala |
| `certificado_por_vencer` | CertExpiringSoon | `cert_days_remaining ≥ 14` | ninguna | No elegible: escala por diseño |

### Niveles de autonomía (`AIOPS_AUTONOMY_LEVEL`)

| Nivel | Comportamiento |
|---|---|
| 0–1 | Solo diagnostica, recomienda y escala (default del repo) |
| 2 | Actúa con aprobación humana: el ciclo se pausa hasta que alguien aprueba desde la UI |
| 3 | Actúa solo en acciones de bajo riesgo (la meta de la tesis) |
| 4 | Además revierte solo |

### La política deniega y escala cuando

- El kill switch está activo.
- La acción está fuera de la lista autorizada o no corresponde a la categoría.
- El nivel de autonomía es menor a 2.
- El incidente no es elegible o tiene severidad crítica.
- El entorno o el servicio no están autorizados.
- No hay diagnóstico con el runbook correcto.
- La confianza es menor al umbral (0.8).
- Se alcanzó el límite de reintentos.
- Se pide un rollback fuera del nivel 4.

---

## 5. Componentes implementados

### Dominio (`domain/aiops_core/`)
- `ciclo.py`: el ciclo, con verificación y confirmación con espera, aprobación humana
  registrada en el dominio y costo del LLM por incidente.
- `politicas.py`: la política determinista.
- `catalogo.py`, `acciones.py`, `modelos.py`.
- `repositorio.py`: puerto de persistencia (memoria por defecto, Postgres en `infra/`).
- `auditoria.py`: registro append-only con callback a Postgres.
- `metricas.py`: TRA, MTTR, rollback y tokens por incidente.
- `evaluacion.py`: definiciones de la tesis y contraste de H1–H3.
- `simulador.py`: banco experimental en memoria.

### Infraestructura (`infra/`)
- `observabilidad.py`: Prometheus/Loki, solo lectura (severidad traducida, etiqueta y
  mountpoint configurables).
- `acciones_k8s.py`: acciones sobre Kubernetes por HTTP, con TLS validado y namespace fijo.
- `alertas_webhook.py`, `alertas_comun.py`: parseo del webhook de Grafana.
- `incidentes_postgres.py`, `auditoria_postgres.py`, `kill_switch.py`, `checkpointer.py`.
- `queue.py`, `redis_client.py`.

### Agente (`agents/aiops/`)
- `agent.yaml`, `prompt.md`, `skills/ciclo-l1/`, `runbooks/RB-001..005`.
- `tools.py`: 14 tools, más `buscar_documentos` por RAG.
- `runtime.py`: arma el `Ciclo` según `AIOPS_*`; `armar()` también construye uno sin
  tocar el singleton.
- `worker_jobs.py`: job de RQ con lock por servicio; `atender_con_agente` es reutilizable
  y mide tokens con un callback.

### API y UI (`app/`)

| Endpoint | Auth | Uso |
|---|---|---|
| `GET /salud` | no | Healthcheck |
| `POST /webhooks/grafana` | sí | Contact point de Grafana: parsea, deduplica y encola |
| `GET /incidentes`, `GET /incidentes/{id}` | sí | Lista y detalle con línea de tiempo |
| `POST /incidentes/{id}/aprobar` y `/rechazar` | sí | Decisión humana (nivel 2) |
| `GET/POST /kill-switch` | sí | Frenar toda ejecución |
| `GET /metricas` | sí | TRA, MTTR, rollback y tokens en JSON |
| `GET /metrics` | no | Formato Prometheus: incidentes por estado, acciones, TRA, MTTR, jobs fallidos, tokens |
| `GET /ui` | no | UI de operación; los datos se piden con el token del operador |

**UI** (`app/ui/index.html`): HTML y JS sin dependencias, tema claro y oscuro.
- Tarjetas de TRA, MTTR, incidentes y kill switch.
- Tabla de incidentes con botones de aprobar y rechazar.
- Línea de tiempo de auditoría y refresco cada 5 s.

**Dashboard de Grafana "AIOps L1"** (`/d/aiops-l1`): TRA, MTTR, incidentes por estado,
alertas activas, acciones y la UI embebida.

### Laboratorio
- **docker compose** (profile `observability`): Prometheus 3.0.1, Grafana 11.4.0,
  RabbitMQ, node_exporter sobre un tmpfs de 50 MB, nginx con un certificado de 3 días,
  blackbox_exporter y la API.
- **k3d** (`aiops-lab`): kube-state-metrics; workloads `api` (readiness rompible) y
  `checkout` (httpd matable); RBAC del agente.
- **Fallas:** `scripts/fallas/*.sh`, con inyección y recuperación para cada categoría.
- **Reglas de Grafana como código:** las 5 del catálogo, con webhook a la API.

### Evaluación (Fase 7)
- `scripts/lab_ciclo.py`: atiende un incidente con `--modo script` (diagnóstico fijo) o
  `--modo llm` (agente real).
- `scripts/experimento.py`: N repeticiones por categoría y CSV fila por fila. Separa los
  errores de infraestructura de las decisiones del agente.
- `scripts/analizar_experimento.py`: tablas Markdown por categoría e hipótesis.
- `docs/protocolo-experimento.md`: protocolo, línea base y checklist para el día de la key.

---

## 6. Seguridad

| Control | Implementación | Verificado |
|---|---|---|
| Lista autorizada de acciones | `ACCIONES_PERMITIDAS`; el servicio se valida con regex | Tests |
| Mínimo privilegio en Kubernetes | Role con `pods: list/delete` y `deployments: get/patch`, solo en `aiops-lab` | En vivo: 403 en secrets y en otros namespaces |
| TLS hacia Kubernetes | Validado con la CA del cluster | En vivo |
| Token de la API | Comparación en tiempo constante (`hmac`); varios tokens para rotar sin corte | Tests |
| UI | Token en `sessionStorage` y cabecera (sin cookie → sin CSRF); `textContent` (sin XSS); CSP `frame-ancestors` | Tests y prueba en el navegador |
| Aprobación humana | Registrada en el dominio (quién, cuándo, veredicto); el LLM no puede aprobarse a sí mismo | Tests y en vivo |
| Secretos | `.env`, el token de Kubernetes y los certificados están en `.gitignore` | Revisión de **todo** el historial de git: nunca se commitearon |
| Kill switch | Tabla en Postgres, se lee en cada evaluación | Tests y en vivo |

**Riesgos aceptados (solo laboratorio, documentados):**

- `GF_PANELS_DISABLE_SANITIZE_HTML=true` es necesario para el iframe: quien edite un
  dashboard podría inyectar HTML/JS.
- Grafana tiene acceso anónimo como Admin (`admin/admin`).
- Los tokens del laboratorio (`lab-secret-token`) y los secretos fijos de
  `docker/garage/garage.toml` son anteriores a esta sesión y el agente no los usa.

---

## 7. Configuración (`.env`, ver `.env.example`)

| Variable | Default | Para qué |
|---|---|---|
| `AIOPS_AUTONOMY_LEVEL` | 1 | Nivel de autonomía |
| `AIOPS_ALLOWED_ENVS` / `AIOPS_ALLOWED_SERVICES` | dev,staging / (todos) | Alcance permitido |
| `AIOPS_CONFIDENCE_THRESHOLD` / `AIOPS_MAX_RETRIES` | 0.8 / 2 | Política |
| `AIOPS_BACKEND` | simulado | `simulado` o `prometheus` |
| `AIOPS_ACTIONS` | ninguna | `ninguna` o `k8s` |
| `AIOPS_K8S_API`, `_NAMESPACE`, `_TOKEN_FILE`, `_CA_FILE` | –, aiops-lab | Backend de Kubernetes |
| `AIOPS_PROMETHEUS_URL`, `AIOPS_LOKI_URL`, `AIOPS_SERVICE_LABEL`, `AIOPS_DISK_MOUNTPOINT` | –, –, service, / | Observabilidad |
| `AIOPS_PERSISTENCIA` | memoria | `memoria` o `postgres` |
| `AIOPS_VERIFY_WINDOW_S` / `_INTERVAL_S` | 0 / 5 | Verificación con espera |
| `AIOPS_CONFIRM_WINDOW_S` | 0 | Reintento de la confirmación sin datos |
| `AIOPS_LOCK_TTL_S` / `AIOPS_LOCK_ESPERA_S` | 900 / 30 | Lock por servicio |
| `AIOPS_JOB_TIMEOUT_S` / `AIOPS_JOB_REINTENTOS` | 900 / 2 | Jobs del worker |
| `AIOPS_API_TOKEN` | – | Token de la API (varios separados por coma) |
| `AIOPS_KILL_SWITCH` / `_FILE` | – | Kill switch en modo memoria |
| `AIOPS_AUDIT_FILE` | – | Auditoría en JSONL |
| `ANTHROPIC_API_KEY` | **vacía** | **Bloqueante para el LLM** |
| `OPENAI_API_KEY` | vacía | Embeddings del RAG de runbooks |

---

## 8. Calidad y pruebas

- **150 tests** (`make test`), más los evals del agente (`make evals`).
- Integración contra servicios reales: Postgres y Redis del compose.
- Los tests usan una base `<base>_test` y la base `/15` de Redis, para no borrar el
  laboratorio.
- **mypy estricto** sin errores en 79 archivos.
- **Cobertura de `domain/`: 99.48 %** (umbral 90 %).
- Cada fase se commiteó con sus verificaciones: 29 commits, detallados en
  `docs/plan-aiops.md`.

---

## 9. Historial por fase

| Fase | Contenido | Estado |
|---|---|---|
| 0 | Validar build, lint, tipos, tests y cobertura en el contenedor | ✅ (sin el demo con LLM) |
| 0.5 | 5 bugs previos: severidad en inglés tratada como `MEDIA`, incidentes reabiertos, aprobación sin registro, etiqueta de servicio ignorada, MTTR mal medido | ✅ |
| 1 | Persistencia en Postgres (Alembic), repositorio, auditoría, kill switch, checkpointer instalado | ✅ |
| 2 | API HTTP, webhook de Grafana, cola RQ, aprobación, métricas | ✅ (sin LLM) |
| 3 | Laboratorio real con los 5 escenarios disparados en vivo | ✅ |
| 4 | Acciones reales sobre Kubernetes con RBAC mínimo y verificación con espera | ✅ |
| 5 | UI embebida en Grafana; aprobación humana de punta a punta | ✅ |
| 6 | Robustez del worker, seguridad del token, costo en tokens, runbook de operación | ✅ |
| 7 | Infraestructura del experimento y análisis | ⏳ falta correrlo con el LLM |

### Bugs reales encontrados en el camino (todos corregidos y con test)

1. Una severidad `critical` de Grafana caía en `MEDIA` → el agente podía autoremediar
   incidentes críticos.
2. Una alerta recurrente reabría el incidente ya cerrado.
3. La aprobación humana dependía solo del framework, sin registro en el dominio.
4. El MTTR se medía desde que el agente abría el incidente, no desde el disparo.
5. El worker escuchaba otra cola de Redis que la del webhook.
6. Faltaba `.dockerignore`: cada build mandaba 73 MB de `.mypy_cache`.
7. **Los tests borraban los datos del laboratorio** (misma base y misma cola).
8. **Las tools del agente no habrían visto el incidente** (dos `Ciclo` distintos). Se
   habría visto recién con el LLM.
9. Escalamiento espurio cuando Prometheus todavía no tenía datos.
10. El escenario `servicio_detenido` se autocuraba: en busybox, `sleep` corre dentro del
    shell y el SIGCHLD lo terminaba.
11. Escalar a 0 réplicas no simula "pod no ready" (sin serie de métrica, Grafana lo lee
    como sano).
12. Las reglas con `severity: critical` impedían que el agente actuara siempre.

---

## 10. Qué falta

### 10.1 Bloqueante: correr el agente con el LLM real

Hasta que no corra, no se sabe si el modelo sigue el ciclo del prompt, si las tools le
resultan claras, cuánto cuesta un incidente ni si el modelo configurado
(`anthropic:claude-sonnet-5`) existe en la API.

Checklist (también en `docs/protocolo-experimento.md`):

1. Poner `ANTHROPIC_API_KEY` en `.env` y reiniciar `api` y `worker`.
2. Verificar el nombre del modelo en `agents/aiops/agent.yaml` y en `ORCHESTRATOR_MODEL`.
3. `make aiops-ingest` (requiere `OPENAI_API_KEY`), para que `buscar_documentos`
   encuentre los runbooks.
4. Una corrida de humo:
   `python scripts/experimento.py --modo llm --nivel 3 --repeticiones 1 --categorias pod_fallido --salida resultados/humo.csv`.
   Revisar la línea de tiempo en la UI.
5. Si hace falta, ajustar el prompt **antes** de las repeticiones (no a mitad).

### 10.2 Fase 7: evaluación de la tesis

- [ ] **Línea base manual:** un operador resuelve las mismas fallas con los runbooks;
      anotar el MTTR y las acciones incorrectas en `resultados/linea_base.csv`. Mejor
      con 3 o más corridas por categoría y más de un operador.
- [ ] **Experimento con LLM:** nivel 3, 5 o más repeticiones por categoría; nivel 1 como
      control (la TRA debe dar 0).
- [ ] **Análisis:** `python -m scripts.analizar_experimento ... --linea-base ...` y
      contraste de H1 (TRA ≥ 30 %), H2 (reducción del MTTR ≥ 20 %) y H3 (sin aumento de
      acciones incorrectas).
- [ ] **Análisis de fallas:** casos no resueltos y por qué.
- [ ] Guardar los CSV crudos con el hash del commit del agente.

### 10.3 Pendientes técnicos (no bloquean la tesis)

| Pendiente | Impacto | Esfuerzo |
|---|---|---|
| Cablear el checkpointer de LangGraph (`Command(resume=...)`) | El nivel 2 con LLM hoy no reanuda el grafo. Por eso el experimento se limita a los niveles 1, 3 y 4 | Medio; requiere la key |
| `disco_lleno` remediable en el laboratorio (backend de acciones para el disco) | Hoy es elegible pero siempre escala y baja la TRA | Medio |
| `cola_detenida` remediable (consumidor en k3d + métricas por cola en RabbitMQ) | Igual que `disco_lleno` | Medio |
| Logs en el laboratorio (Loki/Promtail) | La tool `consultar_logs` no devuelve nada en el laboratorio | Bajo |
| Probar el webhook → worker → LLM de punta a punta con alertas reales | Hoy se probó hasta la llamada al LLM | Bajo, con la key |
| Validar el catálogo y los runbooks con operaciones | Hoy son candidatos de diseño | Depende del equipo |
| ~~Proveedor, modelo y API key desde la UI~~ | ✅ Hecho en el commit `cee84ee` (keys cifradas, token de admin aparte, modelo registrado por incidente) | — |

### 10.4 Para producción (fuera del alcance de la tesis)

- Worker como pod dentro del cluster (hoy usa el token del ServiceAccount desde
  docker compose).
- Plugin de panel de Grafana en lugar del iframe con HTML habilitado; Grafana con
  login real.
- Autenticación por usuario (hoy hay un token compartido) y roles: operador frente a
  administrador.
- Pool de conexiones a Postgres (hoy se abre una conexión por operación).
- Catálogo configurable sin tocar código, multi-tenant y adaptadores para otros
  backends.

---

## 11. Limitaciones a declarar en la tesis

- Laboratorio en **una sola máquina compartida** con otros proyectos: la carga externa
  afecta los tiempos y provoca fallas de infraestructura. El runner las registra aparte
  (`error: infra:`) y el análisis las excluye.
- Solo 2 de las 4 categorías elegibles son remediables en el laboratorio.
- Fallas inyectadas y conocidas: no hay ruido de producción, alertas espurias ni
  incidentes simultáneos.
- Con pocas repeticiones no hay significancia estadística: se reportan valores y `n`.
- El nivel 2 no se evalúa con el LLM (ver el checkpointer).

---

## 12. Cómo levantar todo

```bash
cp .env.example .env               # completar AIOPS_API_TOKEN (y ANTHROPIC_API_KEY)
make build && make migrate
k3d cluster start aiops-lab        # o crear: ver k8s-lab/README.md
kubectl apply -f k8s-lab/
docker compose --profile observability --profile redis up -d
# Grafana: http://localhost:3001/d/aiops-l1   ·   UI: http://localhost:8010/ui
make check                         # lint + tipos + tests + cobertura
```

Para apagar sin perder datos:
`docker compose --profile observability --profile redis stop` y
`k3d cluster stop aiops-lab`.
