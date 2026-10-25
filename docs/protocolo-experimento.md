# Protocolo del experimento (Fase 7)

Cómo medir el agente para contrastar las hipótesis de la tesis:

- **H1:** TRA ≥ 30 %.
- **H2:** reducción del MTTR ≥ 20 % respecto de la resolución manual.
- **H3:** sin aumento de acciones incorrectas respecto de la resolución manual.

Definiciones en `domain/aiops_core/evaluacion.py` (con tests).

## Qué se mide y cómo

| Métrica | Definición | Por qué así |
|---|---|---|
| Elegible | La falla **inyectada** tiene acción autorizada en el catálogo | Si la elegibilidad saliera de la clasificación del agente, un agente que clasifica mal achicaría su propio denominador e inflaría la TRA |
| TRA | Elegibles resueltos y verificados **sin intervención humana** / elegibles | Definición de la tesis |
| MTTR | Del disparo de la alerta (la anomalía visible en Prometheus) al cierre verificado | Mismo inicio y fin en el agente y en la línea base |
| Precisión de clasificación | Categoría detectada = categoría inyectada | |
| Acción incorrecta | Se ejecutó al menos una acción y (se clasificó otra categoría **o** el servicio no quedó verificado sano) | H3 mide actuar mal; abstenerse y escalar no es una acción incorrecta |
| Costo | Tokens del LLM por incidente (entrada + salida), incluido el subagente | Métrica de la tesis |

Con pocas corridas no hay significancia estadística: los resultados se reportan con su
`n`, no con un p-valor. Para un contraste formal hacen falta más repeticiones de las que
permite este laboratorio en una máquina compartida.

## Qué categorías puede resolver el agente en el laboratorio

| Categoría | Acción | ¿Remediable en el lab? | Resultado esperado |
|---|---|---|---|
| `servicio_detenido` | `restart_service` (rollout restart en k3d) | Sí | Resuelto |
| `pod_fallido` | `recreate_pod` (k3d) | Sí | Resuelto |
| `disco_lleno` | `compress_old_logs` | No: no es una operación de Kubernetes | Elegible pero **escala**: baja la TRA |
| `cola_detenida` | `restart_consumer` (rollout restart del consumidor **simulado** en k3d) | Sí (simulado) | Resuelto |
| `certificado_por_vencer` | ninguna | — | No elegible: escala por diseño |

`disco_lleno` cuenta como elegible (lo es según el catálogo) y el agente no la puede
resolver en este laboratorio. Hay que **reportarlo así**, no sacarla del denominador. Si
se la saca, hay que declararlo como limitación.

Con 3 de las 4 categorías elegibles remediables, la TRA máxima con un agente perfecto es
75 % y para llegar al 30 % hace falta al menos un 40 % de éxito en ellas (con solo 2
remediables eran 50 % y 60 %).

## 1. Preparar el laboratorio

```bash
k3d cluster start aiops-lab
docker compose --profile observability --profile redis up -d
docker compose stop worker          # el experimento atiende los incidentes él mismo
kubectl apply -f k8s-lab/            # workloads, kube-state-metrics y RBAC
```

Token del ServiceAccount en `k8s-lab/.secrets/` (ver `k8s-lab/README.md`). Antes de
empezar, la carga de la máquina importa: con otros proyectos consumiendo CPU, el API
server de k3d tiene timeouts y las corridas fallan por infraestructura (quedan marcadas
como `error: infra: ...`, no como fallas del agente).

## 2. Línea base manual

Un operador resuelve **las mismas fallas** a mano, con los runbooks de
`agents/aiops/runbooks/`, sin el agente.

Usar el script guiado, que inyecta la misma falla, mide con el mismo criterio que el
agente y escribe el CSV:

    python -m scripts.linea_base --categoria pod_fallido --operador <nombre> --salida resultados/linea_base.csv

El operador resuelve la falla con los runbooks mientras corre el cronómetro; al dejar de
verse la alerta el script pregunta si hubo alguna acción incorrecta. Repetir ≥ 3 veces por
categoría remediable (`pod_fallido`, `servicio_detenido`), idealmente con más de un
operador. El fin se mide cuando la alerta deja de verse; el agente cierra después de su
propia verificación, así que la comparación es levemente conservadora frente a H2.

Registrar en `resultados/linea_base.csv` (plantilla: `resultados/linea_base.ejemplo.csv`,
columnas `categoria,mttr_s,accion_incorrecta,operador,notas`). Idealmente, 3 o más
corridas por categoría y más de un operador.

## 3. Correr el experimento

```bash
# Plomería, sin API key (no sirve para la tesis: el diagnóstico es fijo)
python scripts/experimento.py --modo script --nivel 3 --repeticiones 3 \
    --salida resultados/script-n3.csv

# El de la tesis (ver el checklist de abajo)
python scripts/experimento.py --modo llm --nivel 3 --repeticiones 5 \
    --salida resultados/llm-n3.csv
```

Cada corrida deja el servicio sano, inyecta la falla, espera la anomalía en Prometheus,
hace atender el incidente y lee el resultado de la API. Las corridas se intercalan entre
categorías. El CSV se escribe fila por fila: si se corta, se retoma con el mismo
`--salida` (agrega filas).

## 4. Analizar

```bash
python -m scripts.analizar_experimento resultados/llm-n3.csv \
    --linea-base resultados/linea_base.csv
```

Imprime tablas Markdown por categoría y el contraste de H1–H3. Si el CSV es de
`--modo script`, el reporte lo advierte.

## Checklist para el día que llegue la API key

1. [ ] `ANTHROPIC_API_KEY=...` en `.env` (nunca commitear) y `docker compose restart api`.
2. [ ] Verificar que el modelo configurado exista: `model:` en `agents/aiops/agent.yaml`
       y `ORCHESTRATOR_MODEL` (default `anthropic:claude-sonnet-5`, sin verificar contra
       la API todavía).
3. [ ] **Una corrida de humo** antes del experimento:
       `python scripts/experimento.py --modo llm --nivel 3 --repeticiones 1
       --categorias pod_fallido --salida resultados/humo-llm.csv`. Mirar en la UI la
       línea de tiempo: ¿el agente siguió el ciclo del prompt?, ¿usó las tools en orden?,
       ¿cuántos tokens gastó?
4. [ ] Si la corrida de humo escaló sin motivo claro, revisar el prompt
       (`agents/aiops/prompt.md`) **antes** de las repeticiones: cambiarlo a mitad del
       experimento invalida la comparación entre corridas.
5. [ ] `make aiops-ingest` (requiere `OPENAI_API_KEY` para los embeddings): sin esto,
       la tool `buscar_documentos` del agente no encuentra los runbooks.
6. [ ] Experimento completo, nivel 3 (y nivel 1 como control: con nivel 1 el agente
       solo recomienda, la TRA debe dar 0).
7. [ ] Línea base manual (sección 2), si no se hizo antes.
8. [ ] Análisis y tablas para la tesis (sección 4). Guardar los CSV crudos con la
       versión del commit del agente (`git rev-parse HEAD`).

## Limitaciones conocidas (a declarar en la tesis)

- Laboratorio en una sola máquina compartida: la carga externa afecta los tiempos
  (MTTR) y provoca fallas de infraestructura (se registran aparte).
- `disco_lleno` no es remediable en este laboratorio (ver arriba).
- El consumidor de `cola_detenida` es una **simulación** (busybox + httpd que publica la métrica
  de RabbitMQ), no un consumidor real de mensajes: la acción `restart_consumer` es real
  (rollout restart en Kubernetes), el consumidor no.
- Nivel 2 no se evalúa con el LLM: la pausa de aprobación se resuelve por el estado en
  Postgres y no reanuda el grafo de LangGraph (checkpointer sin cablear).
- Las fallas son inyectadas y conocidas; no hay ruido de producción, alertas espurias ni
  incidentes simultáneos.
