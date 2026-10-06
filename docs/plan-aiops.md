# Plan: agente `aiops` operativo e integrado con Grafana

Estado de partida (commit "Agrega agente aiops para incidentes L1"): dominio, tools,
runbooks, evals, entorno simulado y adaptador Prometheus/Loki de solo lectura. Hay 84
tests en verde fuera del contenedor. Detalle en `docs/aiops-agent.md` y pendientes sin
verificar en `docs/open-questions.md`.

**Objetivo final:** una alerta de Grafana dispara al agente, que la resuelve o la escala
con evidencia sobre un entorno real de laboratorio. Un humano aprueba o rechaza desde
una UI incrustada en Grafana, y las métricas de la tesis (TRA, MTTR) se ven en un
dashboard.

Reglas que siguen vigentes: la lógica va en `domain/` sin frameworks y con cobertura de
al menos 90%, las invariantes de seguridad viven en el código y no en el prompt, y nunca
se monta `docker.sock`.

---

## Fase 0: Validar lo existente en el contenedor — ✅ parcial, 2026-10-05
- [x] `make build` en verde (`docker compose build app`).
- [x] `make lint` (ruff), `make typecheck` (mypy) y `make test` (85 tests, incluido
      `tests/test_loader_aiops.py`) en verde.
- [x] `make coverage`: `domain/` en 99.19% (umbral 90%).
- [x] Confirmado parcialmente: el loader carga las 14 tools de `aiops` sin error con
      `deepagents` instalado real. Falta confirmar el esquema que recibe el LLM.
      Detalle actualizado en `docs/open-questions.md`.
- [ ] **Pendiente (requiere `ANTHROPIC_API_KEY`/`OPENAI_API_KEY` reales, no disponibles
      en esta sesión):** `make rag-init-db && make aiops-ingest`, `make rag-query
      COLLECTION=aiops_runbooks Q="servicio caido"` (debe devolver RB-001), `make evals`
      y `make aiops-demo` (4 incidentes resueltos, el certificado escalado, TRA impresa).
      Correr estos cuatro con claves reales antes de dar la Fase 0 por cerrada del todo.

**Criterio de cierre:** demo con LLM real que termine sin errores (pendiente de claves).

## Fase 0.5: Correcciones antes de persistir estado — ✅ hecho 2026-10-05
Bugs detectados por análisis de código, corregidos antes de la Fase 1 para no construir
persistencia sobre datos ya torcidos. TDD en los 5 (test que falla por el bug → fix →
verde), con lint/mypy/tests/coverage corridos en el contenedor después de cada uno.
- [x] `infra/observabilidad.py`: `Severidad(labels["severity"])` solo reconocía valores en
      español; una alerta `critical` caía en `MEDIA`. Ahora hay un diccionario de alias
      (`_SEVERIDAD_ALIAS`) que traduce inglés/español, y un valor desconocido se trata como
      `CRITICA` (fail-safe), nunca `MEDIA`. Commit `13919ec`.
- [x] `domain/aiops_core/ciclo.py` (`abrir`): si el último incidente de una alerta ya
      quedó en un estado terminal (`RESUELTO`/`ESCALADO`/`DESCARTADO`), un `alerta_id`
      recurrente crea un incidente nuevo (`INC-{alerta_id}-{n}`) en vez de reabrir el
      viejo. Además, `infra/observabilidad.py` ahora usa `activeAt`/`startsAt` de
      Prometheus para que disparos repetidos de la misma alerta+servicio ya lleguen con
      id distinto. Commit `3a38a84`.
- [x] Aprobación humana (nivel 2): `Ciclo.aprobar(incidente_id, usuario)` /
      `Ciclo.rechazar(incidente_id, usuario, motivo)` registran en `Auditoria` quién,
      cuándo y el veredicto. `ejecutar_remediacion(aprobada=True)` ya no confía en el bool
      del llamador: exige una `Aprobacion` registrada en el dominio para ESE incidente, o
      lanza `ErrorCiclo`. Commit `38d6f5f`.
- [x] `infra/observabilidad.py` (`CONSULTAS_POR_DEFECTO`): las queries PromQL usaban
      `job="{s}"` fijo. Ahora usan `{l}` = la misma etiqueta configurada
      (`AIOPS_SERVICE_LABEL`) que ya usan `alertas_activas()`/`logs()`. Commit `13919ec`.
- [x] `domain/aiops_core/modelos.py`: `Alerta.disparada_en` (epoch, opcional) desde
      `activeAt`/`startsAt` del adaptador real. `metricas.mttr()` mide desde ahí cuando
      está disponible, con fallback a `abierto_en` para el banco simulado. Commit `3a38a84`.

**Criterio de cierre:** ✅ 95 tests en verde (lint/mypy/tests/coverage con exit 0 cada
uno), coverage `domain/` en 99.37%.

## Fase 1: Estado persistente — ✅ hecho 2026-10-05
Hoy el estado del `Ciclo` vive en memoria del proceso y se pierde al reiniciar.
- [x] Tablas en Postgres: `aiops_incidentes` (JSONB + columnas indexadas
      id/estado/servicio), `aiops_eventos_auditoria`, `aiops_kill_switch` (fila única).
      Las acciones y la aprobación quedan dentro del JSONB del incidente, no en tablas
      aparte (decisión tomada en el camino, ver resumen al final de la conversación).
      Commit `6f657f4`.
- [x] Migraciones con **Alembic** (`alembic==1.20.0`, pin real de `uv add`). `make migrate` /
      `make migrate-down`. Verificado upgrade→downgrade→upgrade contra Postgres real.
      Commit `6f657f4`.
- [x] Puerto `RepositorioIncidentes` en `domain/aiops_core/repositorio.py`:
      `RepositorioIncidentesMemoria` (default de `Ciclo`, mismo comportamiento que
      antes) y `RepositorioIncidentesPostgres` en `infra/incidentes_postgres.py`.
      Commits `4bef230`, `ce73431`.
- [x] `Auditoria` gana `on_evento` (callback opcional); `infra/auditoria_postgres.py`
      la conecta a Postgres sin que `domain/` importe `infra/`. El JSONL sigue
      disponible y es independiente. Commit `ce73431`.
- [x] Kill switch en Postgres (`infra/kill_switch.py`), reemplaza la variable de
      entorno/archivo para procesos que ya están corriendo. Commit `ce73431`.
- [x] `langgraph-checkpoint-postgres==3.1.2` instalado y verificado con un `put`/`get`
      real contra Postgres (setup de tablas + checkpoint redondo). **No** cablea
      `create_deep_agent(checkpointer=...)` ni `Command(resume=...)`: eso necesita el
      endpoint `/aprobar` real de la Fase 2, no solo la librería. Commit `433a99d`.
- [x] `AIOPS_PERSISTENCIA=memoria|postgres` en `agents/aiops/runtime.py`: default
      `memoria` (no cambia `make aiops-demo`/evals); `postgres` cablea los 3 adaptadores.

**Criterio de cierre:** ✅ probado con un `Ciclo` nuevo leyendo de Postgres lo que
escribió otro (`tests/test_infra_incidentes_postgres.py::test_sobrevive_acciones_y_aprobacion`),
simulando un reinicio a mitad del incidente. 104 tests en verde, mypy estricto sin
errores, coverage `domain/` 99.40%.

## Fase 2: API HTTP (FastAPI) — ✅ hecho 2026-10-05
- [x] `fastapi`/`uvicorn`/`httpx` agregados; `app/api.py` (no se agregó el servicio al
      compose todavía: se corre con `uvicorn` manualmente o en la Fase 6). Commit `f04959d`.
- [x] `POST /webhooks/grafana`: procesa cada alerta del array `alerts`, dedupea por
      job_id (ver `infra/alertas_webhook.py`: `alerta.id` incluye `fingerprint`/`startsAt`,
      distinto por disparo real) y encola en RQ (`infra/queue.py`, cola `aiops`).
      `status: resolved` se encola igual pero el worker solo audita
      (`Ciclo.notificar_resuelta_en_origen`), nunca fuerza el cierre. **Decisión tomada
      en el camino:** se agregó `Ciclo.abrir_desde_alerta`/`notificar_resuelta_en_origen`
      en vez de un adaptador puente push/pull — el webhook entrega la alerta completa,
      no hace falta que `Ciclo` la busque en `alertas_activas()`. Commits `0a841b3`, `a7a0498`.
- [x] `GET /incidentes`, `GET /incidentes/{id}` con línea de tiempo. En modo
      `AIOPS_PERSISTENCIA=postgres` relee la auditoría desde Postgres
      (`infra/auditoria_postgres.eventos_de_incidente`), no desde `ciclo.auditoria`:
      el proceso que atendió el incidente (el worker) no es el que responde la
      request (la API), así que la `Auditoria` en memoria de la API nunca vio esos
      eventos. Commit `f04959d`.
- [x] `POST /incidentes/{id}/aprobar` y `/rechazar`: envuelven `Ciclo.aprobar`/`rechazar`
      de la Fase 0.5. **No** reanudan `Command(resume=...)` de LangGraph: ver la nota de
      alcance de la Fase 1 sobre el checkpointer — necesita un grafo real pausado por
      `interrupt_on` para probarse, y no hay `ANTHROPIC_API_KEY` en esta sesión. El
      invariante del dominio (`ejecutar_remediacion(aprobada=True)` exige una
      `Aprobacion` registrada) sí queda satisfecho por este endpoint. Commit `f04959d`.
- [x] `GET|POST /kill-switch`: siempre contra la tabla Postgres (`infra/kill_switch.py`),
      sin importar `AIOPS_PERSISTENCIA` del `Ciclo` que responda — Postgres no es
      opcional en este proyecto, a diferencia de Redis/Qdrant. Gobierna la política de
      cualquier `Ciclo` corriendo con `AIOPS_PERSISTENCIA=postgres`. Commit `f04959d`.
- [x] `GET /metricas` (JSON: TRA, MTTR, tasa de rollback) y `GET /metrics` (formato
      Prometheus: `aiops_incidentes_total{estado}`, `aiops_tra_ratio`,
      `aiops_mttr_seconds`; sin token, para que Prometheus/Grafana lo scrapee).
      `aiops_acciones_total{accion,ok}` quedó pendiente (no crítico: se puede derivar
      de `/metricas` o sumarlo después). Commit `f04959d`.
- [x] Autenticación: token compartido simple (`AIOPS_API_TOKEN`), cabecera
      `Authorization: Bearer <token>`.
- [x] Tests con `TestClient`: 6 contra Postgres real (`tests/test_api.py`) + 4 contra
      Redis real (`tests/test_api_webhook.py`, con skip automático si el profile
      `redis` no está levantado — no rompe `make test` para quien no lo tenga arriba).

**Criterio de cierre:** ⚠️ parcial. Un `curl` con un payload de Grafana sí llega a
`abrir_desde_alerta`/auditoría (probado). Lo que falta para el criterio completo
("termina en un incidente resuelto"): que el worker real invoque al agente con un
`ANTHROPIC_API_KEY` válido — `agents/aiops/worker_jobs.py` ya tiene el código
(`build_agent().invoke(...)`), pero no se corrió en vivo en esta sesión.

**Criterio de cierre:** un `curl` con un payload de Grafana termina en un incidente resuelto en el entorno simulado.

## Fase 3: Laboratorio de observabilidad real — ✅ cerrada 2026-10-05
- [x] Servicios: **Prometheus** `v3.0.1`, **Grafana propio** `11.4.0` (provisionado como
      código en `docker/grafana/provisioning/`), **RabbitMQ** con `rabbitmq_prometheus`,
      **node_exporter** `v1.8.2`, **blackbox_exporter** `v0.25.0`, nginx, k3d con
      **kube-state-metrics**. Loki/Promtail/Alloy quedaron fuera: el pipeline de alertas
      no los necesita (las queries de métricas van por Prometheus, no por logs).
- [x] Workloads que fallan de verdad, los 5 escenarios del catálogo:
  - `servicio_detenido`: contenedor `checkout` (nginx), parado/levantado de verdad.
  - `disco_lleno`: `node-exporter-billing` vigilando un **tmpfs de 50MB** (`billing_disk`),
    llenado real con `dd` por `disco-billing-tools`. No arriesga el disco del host.
  - `pod_fallido`: Deployment `api` en k3d, forzado a CrashLoopBackOff con `command: /bin/false`.
  - `cola_detenida`: RabbitMQ sin consumidores (`rabbitmq_queue_consumers = 0`).
  - `certificado_por_vencer`: nginx `gateway` con cert autofirmado de 3 días, sondeado
    por blackbox_exporter (`probe_ssl_earliest_cert_expiry`).
- [x] Inyectores de fallos + recuperación: `scripts/fallas/*.sh` y targets de Makefile
      `falla-<tipo>` / `recuperar-<tipo>` (`servicio`, `disco`, `pod`, `cola`, `certificado`).
- [x] Reglas Grafana-managed como código (`docker/grafana/provisioning/alerting/rules.yaml`):
      `ServiceDown`, `PodFailed`, `QueueStalled`, `DiskUsageHigh` (>85%),
      `CertExpiringSoon` (<14 días). Todas con los `alertname` del catálogo.
- [x] Contact point webhook hacia `POST /webhooks/grafana` con `AIOPS_API_TOKEN`.
- [x] `AIOPS_DISK_MOUNTPOINT` configurable (antes `mountpoint="/"` fijo en la query).
- [x] Clúster k3d `aiops-lab` (1 server + 1 agent), documentado en `k8s-lab/README.md`.

**Criterio de cierre: ✅ los 5 escenarios disparados en vivo** (no mocks), y el webhook
entregado a la API real con 200 OK por cada uno:

| Escenario | Falla inyectada | Métrica observada | Regla | Webhook |
|---|---|---|---|---|
| servicio_detenido | `docker compose stop checkout` | `up{job="checkout"}=0` | ServiceDown | ✅ (y el worker abrió el incidente en Postgres) |
| disco_lleno | `dd` de 45MB al tmpfs de 50MB | `disk=90%` | DiskUsageHigh | ✅ |
| pod_fallido | deployment `command: /bin/false` | `kube_pod_status_ready=0` | PodFailed | ✅ |
| cola_detenida | sin consumidores | `rabbitmq_queue_consumers=0` | QueueStalled | ✅ |
| certificado_por_vencer | cert de 3 días | `cert_days_remaining≈3` | CertExpiringSoon | ✅ |

Cada falla se recupera y la regla vuelve a `inactive` (verificado con disco).

**Lo que la Fase 3 NO prueba, explícito:**
- Que el agente resuelva el incidente de punta a punta con el LLM real: el worker llega
  hasta la llamada al LLM y falla limpio por falta de `ANTHROPIC_API_KEY` (límite de la Fase 2).
- Escenarios sin acción automática (`certificado_por_vencer`) solo se prueban en detección.

**Hallazgos del camino (documentados en los commits):**
- `kube_pod_status_ready` no reporta `0` para un pod que no existe: `sum()` sobre serie
  vacía da NoData, y `noDataState: OK` lo lee como sano. Por eso `pod_fallido` se simula
  con un pod que existe pero no está ready (CrashLoop), no escalando a 0 réplicas.
- Git Bash convierte argumentos `/path` a rutas de Windows; los scripts lo desactivan
  con `MSYS_NO_PATHCONV=1`.

## Fase 4: Backend de acciones real (Kubernetes/k3d) — ✅ cerrada 2026-10-06
- [x] `infra/acciones_k8s.py` (`BackendKubernetes`): HTTP stdlib contra la API de
      Kubernetes, sin dependencias nuevas. `recreate_pod` → borra pods `app=<servicio>`;
      `restart_service`/`restart_consumer` → rollout restart del Deployment (anotación
      del template, igual que `kubectl rollout restart`). `compress_old_logs`/
      `restore_compressed_logs` no son operaciones de Kubernetes: fallan con
      `RuntimeError` y el agente escala, sin inventar una equivalencia.
- [x] RBAC mínimo (`k8s-lab/rbac-aiops.yaml`): `pods: list/delete/deletecollection` y
      `deployments: get/patch`, solo en `aiops-lab`. **Verificado en vivo:** puede listar
      pods de `aiops-lab`; recibe 403 en secrets y en otros namespaces.
- [x] Respeta `timeout_s` (timeout del request HTTP); el namespace lo fija la
      configuración, no el LLM; el servicio ya llega validado por el dominio. Un 403 del
      RBAC sale como `RuntimeError` con el código (queda en el paquete de escalamiento).
- [x] `AIOPS_ACTIONS=ninguna|k8s` en `agents/aiops/runtime.py` (con `AIOPS_BACKEND=prometheus`).
- [x] Verificación con espera: `Ciclo(verificacion_ventana_s, verificacion_intervalo_s)`
      sondea hasta recuperar o agotar la ventana (`AIOPS_VERIFY_WINDOW_S`/
      `_INTERVAL_S`). Ventana 0 = una lectura, como antes. Tests con reloj/sueño falsos.
- [x] Workload de `pod_fallido` rediseñado: readiness rota (borrar `/tmp/ok`) que **sí**
      arregla la acción autorizada. El CrashLoop de la Fase 3 no servía para probar
      remediación: recrear el pod no lo cura.
- [x] `scripts/lab_ciclo.py`: el ciclo L1 completo sin LLM contra backends reales.

**Desvío de la decisión 13 (in-cluster):** el worker sigue en docker compose y usa el
token del ServiceAccount desde afuera. El límite de seguridad es el mismo (el RBAC lo
impone el API server, no la ubicación del proceso); correr el worker como pod exige
además un pipeline para importar la imagen a k3d, que no aporta a la tesis. El token
vive en `k8s-lab/.secrets/` (ignorado por git).

**Criterio de cierre: ✅ en vivo, sin mocks y sin LLM:**
`pod_ready=0 (Prometheus) → anomalía confirmada → pod_fallido elegible → recreate_pod
(API de Kubernetes, RBAC mínimo) → 15s de sondeo → pod_ready=1 → CERRADO
resuelto_autonomo=True`, persistido en Postgres.

**Hallazgos:**
- Una primera corrida arrancó justo después de que la máquina se suspendiera: Prometheus
  no tenía scrapes recientes, `pod_ready` vino vacío y el agente **escaló en vez de
  actuar** (correcto: sin evidencia no ejecuta). `confirmar_anomalia` hace una sola
  lectura; un reintento corto ante "sin datos" evitaría escalamientos espurios. Queda
  como mejora menor, no se hizo.
- Las reglas de laboratorio `ServiceDown` y `PodFailed` tenían `severity: critical`, y la
  política nunca deja actuar al agente sobre severidad crítica. Bajadas a `alta`: son
  candidatos L1. Sin este cambio, el pipeline real habría escalado siempre.

## Fase 5: UI integrada en Grafana — ✅ cerrada 2026-10-06
- [x] UI servida por la API (`GET /ui`, `app/ui/index.html`): HTML + JS vanilla, sin
      build ni dependencias. Tarjetas de TRA/MTTR/incidentes/kill switch, tabla de
      incidentes, aprobar/rechazar (pide motivo al rechazar), línea de tiempo de
      auditoría y refresco cada 5s. Tema claro/oscuro. **Sin chat** (decisión 4).
- [x] Seguridad de la UI:
  - La página se sirve sin token pero no trae datos: los pide a la API con el token que
    el operador ingresa (`sessionStorage`), por cabecera `Authorization` — no por
    cookie, así que no hay superficie de CSRF.
  - Todo dato se pinta con `textContent` (sin `innerHTML`): un nombre de servicio o un
    motivo con HTML no se ejecuta. Verificado por test.
  - El usuario que aprueba queda en la auditoría (`aprobacion: {usuario, veredicto}`).
  - `Content-Security-Policy: frame-ancestors` configurable (`AIOPS_UI_FRAME_ANCESTORS`,
    default `'self' http://localhost:3001`).
- [x] Dashboard provisionado "AIOps L1" (`docker/grafana/dashboards/aiops.json`): TRA y
      MTTR (stat), incidentes por estado, alertas L1 activas (alertlist), acciones
      ejecutadas, y la UI en un panel Text con `<iframe>`.
  - **Riesgo documentado:** el iframe exige `GF_PANELS_DISABLE_SANITIZE_HTML=true`;
    con eso, quien pueda editar un dashboard puede inyectar HTML/JS en Grafana.
    Aceptable en el laboratorio local; en una instancia compartida, un plugin de panel.
- [x] Prometheus scrapea `/metrics` de la API (`job: aiops-api`). Se agregó
      `aiops_acciones_total{accion,ok}` (pendiente desde la Fase 2).
- [x] `scripts/lab_ciclo.py` soporta nivel 2: ante "requiere aprobación" espera la
      decisión registrada en Postgres por la UI y recién entonces ejecuta (lo que haría
      el agente pausado por `interrupt_on`, sin LLM).
- [ ] Opcional (no hecho): plugin de app de Grafana con entrada propia en el menú.

**Criterio de cierre: ✅ en vivo**, con autonomía 2: `pod_ready=0` → anomalía
confirmada → la política responde "requiere aprobación" y el ciclo **pausa** → la UI
lo muestra como "esperando aprobación" → se aprueba (`marcelo@equipo`) → la política
permite → `recreate_pod` en k3d → 32s de sondeo → `pod_ready=1` → **CERRADO con
`resuelto_autonomo=False`** (correcto: con aprobación humana no cuenta para la TRA). La
línea de tiempo registra quién aprobó.

**Límite honesto de la verificación:** no había navegador disponible en la sesión, así
que el clic en "Aprobar" se emuló con la misma petición que hace el botón (mismo
método, ruta con el id codificado con `encodeURIComponent` — `:` como `%3A` —, mismas
cabeceras y cuerpo). Se verificó además que `/ui` responde 200 con la CSP, que el
dashboard carga con sus 6 paneles y que Prometheus scrapea la API.

**Clic real verificado despues:** el usuario aprobo un incidente desde la UI en el
navegador (`decision: aprobado por marcelo`) y el ciclo recreo el pod, verifico y
cerro con `resuelto_autonomo=False`.

## Fase 6: Endurecimiento y operación
- [ ] Langfuse (profile ya existente) o métricas propias para el costo de tokens por incidente (métrica de la tesis).
- [ ] Límite de concurrencia: un incidente por servicio a la vez (lock en Redis).
- [ ] Reintentos y timeouts del worker, y una cola de mensajes fallidos.
- [ ] Revisión de seguridad: secretos fuera del repo, `AIOPS_API_TOKEN` rotable y
      principio de mínimo privilegio verificado (RBAC del ServiceAccount de la Fase 4).
- [ ] README y `docs/aiops-agent.md` actualizados, incluido un runbook de operación del propio agente.

## Fase 7: Evaluación de la tesis
- [ ] Línea base: atender los mismos escenarios a mano (o con datos históricos) midiendo
      MTTR con el mismo inicio (disparo de la alerta) y el mismo fin (verificación).
- [ ] Ejecutar N repeticiones por categoría y nivel de autonomía (`scripts/experimento.py`)
      y exportar CSV con TRA, MTTR, precisión de clasificación y diagnóstico, acciones correctas o bloqueadas, rollbacks y escalamientos.
- [ ] Contrastar H1 (TRA ≥ 30%), H2 (reducción de MTTR ≥ 20%) y H3 (sin aumento de acciones incorrectas).
- [ ] Analizar los fallos y los casos no resueltos.

---

## Orden y dependencias
0 → 0.5 → 1 → 2 → 3 → (4 y 5 en paralelo) → 6 → 7. La fase 2 puede probarse completa con
el entorno simulado antes de tener el laboratorio de la fase 3.

## Decisiones tomadas (2026-10-05)
1. **Laboratorio:** Kubernetes (k3d), no compose puro. El catálogo ya asume
   `pod_fallido`/`kube-state-metrics`, y compose no puede reiniciar servicios sin montar
   `docker.sock`, prohibido por las reglas del framework.
2. **Grafana:** propio en el compose del laboratorio, provisionado como código. La
   integración del agente con Grafana ya es agnóstica a la instancia (webhook estándar +
   lectura directa de Prometheus/Loki); esta decisión es solo sobre dónde corre el
   laboratorio de pruebas de la tesis.
3. **Broker de cola:** RabbitMQ (no Redis). Coincide con la métrica
   `rabbitmq_queue_consumers` que `infra/observabilidad.py` ya asume, y es más completo
   como cola de trabajo real (acks, dead-letter, consumidores nativos).
4. **Chat de la UI:** postergado. No aporta a H1 (TRA) / H2 (MTTR) / H3 (acciones
   correctas); se evalúa como extra después de la Fase 7.
5. **Bugs de la Fase 0.5:** se corrigen antes de la Fase 1, no junto con ella, para no
   construir persistencia sobre datos ya torcidos (en particular el MTTR).
6. **ID de incidente:** `INC-{alerta_id}-{startsAt}` (o fingerprint del disparo). Un
   incidente `RESUELTO`/`ESCALADO`/`DESCARTADO` nunca se reabre.
7. **Aprobación humana:** se registra en el dominio (quién, cuándo, veredicto), no solo
   en el `interrupt_on` del framework.
8. **Migraciones:** Alembic (nueva dependencia), no scripts de un solo uso.
9. **Checkpointer:** `langgraph-checkpoint-postgres==3.1.2` (PyPI, 2026-08-07).
10. **Payload del webhook de Grafana:** se procesa cada alerta del array `alerts`;
    `status: resolved` audita pero no fuerza el cierre automático del incidente.
11. **Autenticación de la API:** token compartido simple (`AIOPS_API_TOKEN`), sin tabla
    de usuarios/roles.
12. **Kill switch:** tabla en Postgres (no variable de entorno ni archivo), compartida
    por todos los procesos (`api`, `worker`).
13. **Acceso de `BackendAcciones` al clúster:** in-cluster vía ServiceAccount con RBAC
    mínimo, no kubeconfig externo.

## Fuera de alcance por ahora (backlog)
- **"Servicio lento/degradado"** como categoría nueva (latencia p95, error rate) más allá
  de las 5 categorías binarias del catálogo actual. Requiere decidir señal sana, runbook
  y si la acción es `restart_service`, un scale-up u otra. Se evalúa después de cerrar las
  5 categorías existentes sobre el laboratorio real.
