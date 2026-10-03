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
| RAG / base de conocimiento | `rag:` en `agent.yaml` → tool `buscar_documentos` sobre `agents/aiops/runbooks/` |
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
make aiops-ingest      # indexa los runbooks (requiere OPENAI_API_KEY y make rag-init-db)
make aiops-demo        # LLM + banco simulado, nivel 3; imprime estados y TRA
make test && make evals
```

`AIOPS_BACKEND=prometheus` conecta Prometheus/Loki reales en **solo lectura**: no hay
backend de acciones real, así que toda ejecución falla y el agente escala. Para ejecutar
de verdad hay que implementar `BackendAcciones` (por ejemplo con la API de Kubernetes) y
cablearlo en `agents/aiops/runtime.py`.

## Pendiente

- Endpoint HTTP / webhook de Alertmanager y UI (embebible en Grafana).
- Backend de acciones real.
- Verificación con espera y reintentos (hoy hace una sola lectura).
- Línea base de MTTR con datos reales y validación del catálogo L1 con operaciones.
- Medición del costo en tokens.
