# Agente `aiops`: incidentes L1

Implementación del agente de la tesis *"Diseño, implementación y evaluación de un
agente autónomo de AIOps integrado con una plataforma de observabilidad para la
detección y resolución automatizada de incidentes recurrentes de nivel 1"*.

## Un solo agente

La tesis exige un único agente con un único ciclo de decisión. Aquí es el subagente
`aiops` (`agents/aiops/`). El orquestador de `app/main.py` solo enruta el pedido y no
toma decisiones operativas. El detector, el clasificador, la política, el ejecutor, el
verificador, el rollback y la auditoría son **funciones** de `domain/aiops_core/` que
el agente invoca como tools. No son agentes.

## Mapa tesis → código

| Componente de la tesis | Código |
|---|---|
| Adaptador de observabilidad | Puerto `domain/aiops_core/observabilidad.py`; Prometheus/Loki en `infra/observabilidad.py` |
| Detector/confirmador de anomalías | `Ciclo.confirmar_anomalia` contrasta la alerta con la señal sana de su categoría |
| Motor de clasificación y elegibilidad | `catalogo.py` + `Ciclo.clasificar` |
| Motor de diagnóstico | El LLM, con la evidencia de las tools; queda registrado con `registrar_diagnostico` (causa, confianza, runbook) |
| RAG / base de conocimiento | Tool `buscar_conocimiento` (`agents/aiops/conocimiento.py`): Gemini + pgvector, filtrada por el servicio del incidente, con citas que el dominio verifica. Informa, no autoriza. El runbook de la categoría sigue llegando por id con `clasificar_incidente` |
| Motor de políticas | `politicas.py` (determinista, no lo decide el LLM) |
| Ejecutor | `acciones.py`: lista autorizada y servicio validado |
| Verificador | `Ciclo.verificar` vuelve a leer la telemetría |
| Gestor de rollback | `Ciclo.revertir` (solo nivel 4 y si el runbook lo define) |
| Escalamiento humano | `Ciclo.escalar` entrega un paquete con evidencia y acciones |
| Auditoría | `auditoria.py` (memoria y, opcionalmente, JSONL en `AIOPS_AUDIT_FILE`) |
| Métricas (TRA, MTTR, rollback) | `metricas.py` |
| Banco experimental con inyección de fallos | `simulador.py` |

## Controles obligatorios de la tesis

| Control | Dónde se impone |
|---|---|
| Lista autorizada de acciones | `ACCIONES_PERMITIDAS` y política |
| Control de acceso por servicio y entorno | `AIOPS_ALLOWED_ENVS`, `AIOPS_ALLOWED_SERVICES` |
| Umbral de confianza | `AIOPS_CONFIDENCE_THRESHOLD` |
| Límite de reintentos | `AIOPS_MAX_RETRIES` |
| Timeout operacional | `AccionDef.timeout_s`, que se pasa al backend |
| Verificación posterior independiente | `cerrar` falla si `verificar` no dio recuperado |
| Kill switch | `AIOPS_KILL_SWITCH=1` o el archivo `AIOPS_KILL_SWITCH_FILE`; bloquea toda ejecución, nunca el escalamiento |
| Rollback | Nivel 4 y solo si la categoría tiene rollback |
| Escalamiento con evidencia | `escalar_a_humano` |

Las invariantes viven en `domain/`, no en el prompt. Aunque el LLM se salte un paso,
el código no ejecuta sin política ni cierra sin verificación.

## Niveles de autonomía (`AIOPS_AUTONOMY_LEVEL`, por defecto 1)

| Nivel | Comportamiento |
|---|---|
| 0-1 | No ejecuta; diagnostica, recomienda y escala |
| 2 | `ejecutar_remediacion` responde "requiere aprobación" y el agente usa `ejecutar_remediacion_con_aprobacion`, que queda pausada (`require_approval`) |
| 3 | Ejecuta solo las acciones de bajo riesgo |
| 4 | Además revierte solo |

Un incidente resuelto con aprobación humana **no** cuenta para la TRA.

## Uso

```bash
make aiops-ingest      # indexa runbooks y corpus/ (requiere la key de Gemini cargada desde la UI)
make aiops-demo        # LLM + banco simulado, nivel 3; imprime estados y TRA
make test && make evals
```

`AIOPS_BACKEND=prometheus` conecta Prometheus/Loki reales en **solo lectura**: no hay
backend de acciones real, así que toda ejecución falla y el agente escala. Para ejecutar
de verdad hay que implementar `BackendAcciones` (por ejemplo con la API de Kubernetes) y
cablearlo en `agents/aiops/runtime.py`.

## Estado (ver docs/plan-aiops.md para el detalle fase por fase)

Fases 0 a 6 completas, probadas contra un laboratorio real (Prometheus, Grafana,
RabbitMQ, k3d). El agente:

- recibe alertas de Grafana por webhook, las encola en RQ y las atiende un worker con
  lock por servicio, reintentos, timeout y cola de fallidos;
- persiste incidentes y auditoría en Postgres;
- actúa sobre Kubernetes con un ServiceAccount de RBAC mínimo (`AIOPS_ACTIONS=k8s`) y
  verifica la recuperación sondeando (`AIOPS_VERIFY_WINDOW_S`);
- pide aprobación humana en nivel 2 desde una UI embebida en Grafana (`/ui`);
- mide TRA, MTTR y el costo en tokens por incidente (`/metricas`, `/metrics`).

Operación: `docs/runbook-operacion.md`.

## Pendiente

- **Probar el agente con el LLM real.** Todas las corridas de punta a punta se hicieron
  con `scripts/lab_ciclo.py`, que recorre el ciclo con un diagnóstico fijo. El código
  que invoca al LLM está cableado y probado con un agente falso, pero nunca corrió con
  `ANTHROPIC_API_KEY`. Es condición para que la evaluación (Fase 7) mida al agente y no
  al script.
- Cablear el checkpointer a `create_deep_agent`/`Command(resume=...)`: hoy la pausa de
  nivel 2 se resuelve por el estado en Postgres, no reanudando el grafo de LangGraph.
- Fase 7: línea base de MTTR, corridas repetidas por categoría y contraste de H1–H3.
- Validar el catálogo L1 y los runbooks con operaciones (siguen siendo candidatos de
  diseño).
