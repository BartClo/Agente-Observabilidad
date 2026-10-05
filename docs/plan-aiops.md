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

## Fase 2: API HTTP (FastAPI)
- [ ] Añadir `fastapi` y `uvicorn` y exponer `app/api.py` en el servicio `app` del compose.
- [ ] `POST /webhooks/grafana`: recibe el payload de alertas de Grafana (contact point de
      tipo webhook; trae un array `alerts`), valida el token compartido y procesa **cada
      alerta del array por separado**, deduplicando por fingerprint. Una alerta con
      `status: resolved` para un incidente que el agente no cerró todavía se audita pero
      no fuerza el cierre automático (queda para revisión). Encola cada incidente nuevo en
      RQ (`infra/queue.py`, profile `redis`); el worker ejecuta el agente.
- [ ] `GET /incidentes`, `GET /incidentes/{id}` (con línea de tiempo de auditoría).
- [ ] `POST /incidentes/{id}/aprobar` y `/rechazar`: registran la aprobación en el dominio
      (`Ciclo.aprobar`/`rechazar` de la Fase 0.5, con el usuario que la autentica) y
      reanudan el grafo pausado por `interrupt_on` (Command resume de LangGraph).
- [ ] `GET|POST /kill-switch`: lee y activa el kill switch sobre la tabla `kill_switch` de
      Postgres (Fase 1), con auditoría del cambio. Reemplaza la variable de entorno/archivo
      actual, que no sirve para un proceso ya corriendo.
- [ ] `GET /metricas`: TRA, MTTR, tasa de rollback y escalamientos, en JSON.
- [ ] `GET /metrics` en formato Prometheus (`aiops_incidentes_total{estado}`,
      `aiops_mttr_seconds`, `aiops_tra_ratio`, `aiops_acciones_total{accion,ok}`) para graficar en Grafana.
- [ ] Autenticación: token compartido simple (`AIOPS_API_TOKEN`) validado en cabecera
      `Authorization`; alcanza para el alcance de la tesis (sin tabla de usuarios/roles).
- [ ] Tests de la API con `TestClient` y payloads reales de Grafana guardados como fixtures
      (incluyendo payload con `alerts` agrupadas y uno con `status: resolved`).

**Criterio de cierre:** un `curl` con un payload de Grafana termina en un incidente resuelto en el entorno simulado.

## Fase 3: Laboratorio de observabilidad real (docker compose, profile `observability`)
- [ ] Servicios: Prometheus, Loki, Promtail/Alloy, **Grafana propio** (versión fijada y
      verificada, provisionado como código en `docker/grafana/provisioning/`) y
      node_exporter.
- [ ] Workloads de prueba que fallen de verdad: un servicio HTTP que se pueda tumbar, un
      volumen que se llene de logs, un deployment de k3d para `pod_fallido` y un
      consumidor sobre una cola **RabbitMQ** (nuevo servicio del compose/laboratorio;
      coincide con la métrica `rabbitmq_queue_consumers` ya asumida en
      `infra/observabilidad.py`).
- [ ] Inyectores de fallos (`scripts/fallas/*.sh` o `make falla-<tipo>`) que reproduzcan las 5 categorías.
- [ ] Reglas de alerta de Grafana provisionadas como código (`docker/grafana/provisioning/`)
      con los `alertname` del catálogo (`ServiceDown`, `DiskUsageHigh`, `PodCrashLooping`/`PodFailed`, `QueueStalled`, `CertExpiringSoon`)
      y las etiquetas `service`, `env` y `severity`.
- [ ] Contact point webhook hacia `POST /webhooks/grafana`, con el token de `AIOPS_API_TOKEN`.
- [ ] Clúster **k3d** para el laboratorio (decidido: Kubernetes, no compose puro — el
      catálogo ya asume `pod_fallido`/`kube-state-metrics`, y compose no puede reiniciar
      servicios sin montar `docker.sock`, prohibido). Añadir kube-state-metrics.
- [ ] Ajustar `CONSULTAS_POR_DEFECTO` de `infra/observabilidad.py` a las métricas reales
      del laboratorio k3d + RabbitMQ (ya corregido para usar `AIOPS_SERVICE_LABEL` en la Fase 0.5).

**Criterio de cierre:** inyectar un fallo hace que salte la alerta en Grafana y llegue el webhook a la API.

## Fase 4: Backend de acciones real (Kubernetes/k3d)
- [ ] Implementar `BackendAcciones` en `infra/acciones_k8s.py` contra la API de
      Kubernetes, con un **ServiceAccount in-cluster** (el `worker`/`app` corre dentro del
      clúster k3d) y RBAC mínimo: solo `delete pod` y `rollout restart` en el namespace
      del laboratorio. Sin kubeconfig externo que proteger fuera del clúster.
- [ ] Respetar `timeout_s`, que no haya parámetros libres y validar el servicio (ya está en domain).
- [ ] Cablearlo en `agents/aiops/runtime.py` con `AIOPS_BACKEND=prometheus` + `AIOPS_ACTIONS=k8s`.
- [ ] Verificación con espera: `Ciclo.verificar` con sondeo (`intervalo`, `ventana`) y tests.

**Criterio de cierre:** el agente reinicia de verdad un servicio del laboratorio y verifica su recuperación.

## Fase 5: UI integrada en Grafana
- [ ] UI web servida por la API (`/ui`): lista de incidentes, línea de tiempo, botones
      Aprobar/Rechazar, kill switch y tarjetas de TRA y MTTR. **Sin chat** (postergado:
      no aporta a H1/H2/H3; se evalúa como extra después de la Fase 7).
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
