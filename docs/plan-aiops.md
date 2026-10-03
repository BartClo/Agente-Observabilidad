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

## Fase 0: Validar lo existente en el contenedor
- [ ] `make build && make check && make evals` en verde, incluido `tests/test_loader_aiops.py`.
- [ ] Confirmar que LangChain arma bien el esquema de las tools envueltas con `functools.wraps`.
      Si no, quitar el decorador `_seguro` y capturar errores en cada tool.
- [ ] `make rag-init-db && make aiops-ingest` y comprobar que `make rag-query COLLECTION=aiops_runbooks Q="servicio caido"` devuelve RB-001.
- [ ] `make aiops-demo` con `ANTHROPIC_API_KEY`: 4 incidentes resueltos, el certificado escalado, TRA impresa.
- [ ] Cerrar o actualizar las entradas de `docs/open-questions.md` según el resultado.

**Criterio de cierre:** demo con LLM real que termine sin errores.

## Fase 1: Estado persistente
Hoy el estado del `Ciclo` vive en memoria del proceso y se pierde al reiniciar.
- [ ] Tablas en Postgres para `incidentes`, `acciones` y `eventos_auditoria`
      (migración en `docker/postgres-init/` o script en `domain`/`infra`).
- [ ] Puerto `RepositorioIncidentes` en `domain/aiops_core/` con una implementación en
      memoria (tests) y otra en Postgres (`infra/`).
- [ ] `Auditoria` también persiste en Postgres. El JSONL queda como opción.
- [ ] Checkpointer de LangGraph sobre Postgres (`langgraph-checkpoint-postgres`, versión
      resuelta con `uv add` y no adivinada), necesario para reanudar las pausas de aprobación.

**Criterio de cierre:** reiniciar `app` a mitad de un incidente y retomarlo.

## Fase 2: API HTTP (FastAPI)
- [ ] Añadir `fastapi` y `uvicorn` y exponer `app/api.py` en el servicio `app` del compose.
- [ ] `POST /webhooks/grafana`: recibe el payload de alertas de Grafana (contact point de
      tipo webhook), valida un token compartido, deduplica por fingerprint y encola el
      incidente en RQ (`infra/queue.py`, profile `redis`). El worker ejecuta el agente.
- [ ] `GET /incidentes`, `GET /incidentes/{id}` (con línea de tiempo de auditoría).
- [ ] `POST /incidentes/{id}/aprobar` y `/rechazar`: reanudan el grafo pausado por
      `interrupt_on` (Command resume de LangGraph). Registrar quién aprobó.
- [ ] `POST /incidentes/{id}/chat`: pregunta en lenguaje natural al agente sobre el incidente.
- [ ] `GET|POST /kill-switch`: lee y activa el kill switch, con auditoría.
- [ ] `GET /metricas`: TRA, MTTR, tasa de rollback y escalamientos, en JSON.
- [ ] `GET /metrics` en formato Prometheus (`aiops_incidentes_total{estado}`,
      `aiops_mttr_seconds`, `aiops_tra_ratio`, `aiops_acciones_total{accion,ok}`) para graficar en Grafana.
- [ ] Autenticación: token de API y, si Grafana hace de proxy, cabecera de usuario.
- [ ] Tests de la API con `TestClient` y payloads reales de Grafana guardados como fixtures.

**Criterio de cierre:** un `curl` con un payload de Grafana termina en un incidente resuelto en el entorno simulado.

## Fase 3: Laboratorio de observabilidad real (docker compose, profile `observability`)
- [ ] Servicios: Prometheus, Loki, Promtail/Alloy, Grafana y node_exporter, con versiones fijadas y verificadas.
- [ ] Workloads de prueba que fallen de verdad: un servicio HTTP que se pueda tumbar, un
      volumen que se llene de logs y un consumidor de cola sobre Redis o RabbitMQ.
- [ ] Inyectores de fallos (`scripts/fallas/*.sh` o `make falla-<tipo>`) que reproduzcan las 5 categorías.
- [ ] Reglas de alerta de Grafana provisionadas como código (`docker/grafana/provisioning/`)
      con los `alertname` del catálogo (`ServiceDown`, `DiskUsageHigh`, `PodCrashLooping`/`PodFailed`, `QueueStalled`, `CertExpiringSoon`)
      y las etiquetas `service`, `env` y `severity`.
- [ ] Contact point webhook hacia `POST /webhooks/grafana`.
- [ ] Ajustar `CONSULTAS_POR_DEFECTO` de `infra/observabilidad.py` a las métricas reales del laboratorio.
      Si se usa Kubernetes (kind/k3d), añadir kube-state-metrics.

**Criterio de cierre:** inyectar un fallo hace que salte la alerta en Grafana y llegue el webhook a la API.

## Fase 4: Backend de acciones real
- [ ] Implementar `BackendAcciones` en `infra/acciones_*.py`:
  - Opción A (recomendada si el laboratorio es Kubernetes): API de Kubernetes con un
    ServiceAccount y RBAC mínimo (solo `delete pod`, `rollout restart` en el namespace del laboratorio).
  - Opción B (compose): un "ejecutor" sidecar con endpoints fijos por acción y sin shell.
    Sigue prohibido montar `docker.sock`.
- [ ] Respetar `timeout_s`, que no haya parámetros libres y validar el servicio (ya está en domain).
- [ ] Cablearlo en `agents/aiops/runtime.py` con `AIOPS_BACKEND=prometheus` + `AIOPS_ACTIONS=k8s|sidecar`.
- [ ] Verificación con espera: `Ciclo.verificar` con sondeo (`intervalo`, `ventana`) y tests.

**Criterio de cierre:** el agente reinicia de verdad un servicio del laboratorio y verifica su recuperación.

## Fase 5: UI integrada en Grafana
- [ ] UI web servida por la API (`/ui`): lista de incidentes, línea de tiempo, botones
      Aprobar/Rechazar, chat, kill switch y tarjetas de TRA y MTTR.
- [ ] Cabeceras: permitir framing desde el origen de Grafana (`Content-Security-Policy: frame-ancestors <grafana>`).
- [ ] Dashboard provisionado "AIOps" con:
  - Panel Text con un `<iframe src="/ui">`. Requiere `disable_sanitize_html = true` en
    `grafana.ini`; documentar el riesgo.
  - Paneles de series temporales sobre `/metrics` (incidentes por estado, MTTR, TRA, acciones).
- [ ] Opcional, fase posterior: plugin de tipo app de Grafana si se quiere una entrada propia en el menú.

**Criterio de cierre:** aprobar una acción de nivel 2 desde el iframe en Grafana y ver el incidente resuelto.

## Fase 6: Endurecimiento y operación
- [ ] Langfuse (profile ya existente) o métricas propias para el costo de tokens por incidente (métrica de la tesis).
- [ ] Límite de concurrencia: un incidente por servicio a la vez (lock en Redis).
- [ ] Reintentos y timeouts del worker, y una cola de mensajes fallidos.
- [ ] Revisión de seguridad: secretos fuera del repo, tokens rotables y principio de mínimo privilegio verificado.
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
0 → 1 → 2 → 3 → (4 y 5 en paralelo) → 6 → 7. La fase 2 puede probarse completa con el
entorno simulado antes de tener el laboratorio de la fase 3.

## Decisiones abiertas (preguntar al usuario)
1. Laboratorio sobre Kubernetes (kind/k3d) o solo docker compose. Esto define el backend de la fase 4.
2. Grafana propio en el compose o una instancia institucional existente, y su versión.
3. Broker de cola para el escenario `cola_detenida`: Redis (ya está) o RabbitMQ.
4. Si el chat de la UI es necesario para la tesis o queda como extra.
