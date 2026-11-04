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
    python -m scripts.linea_base --categoria pod_fallido/config_invalida --operador <nombre>

El cronómetro corre de t2 (alerta disparada) a t5 (señal sana, con el mismo verificador externo
que el agente). Al terminar, el operador clasifica su acción con la Tabla 15 de la tesis. Si no
se recupera en 15 minutos, el caso se registra como no resuelto. Repetir ≥ 3 veces por escenario.

El CSV tiene las columnas `categoria,variante,mttr_s,resultado,accion_incorrecta,operador,notas`.

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

### Rigor de las corridas (tesis, 6.5 y 6.6)

- `--semilla N` sortea el orden dentro de cada bloque y queda en el CSV. Sin ella se elige una
  y se imprime. `--variantes` agrega las 4 variantes confusoras, 3 veces cada una.
- Antes de cada corrida el servicio tiene que estar sano 60 s seguidos.
- Marcas `t0`–`t5`. `t5` lo pone un verificador externo que consulta la señal **sana** y exige
  dos lecturas seguidas. `mttr_s` es t5 − t2; el cierre del agente va en `cierre_interno_s`.
- Sin recuperación en 15 min desde t2, `t5` queda vacío: el caso cuenta como no resuelto.
- `--fase final` exige `--via webhook`, porque t2 es la alerta de Grafana.
- Brazos: `--modo llm --nivel 3` (principal), `--modo llm --nivel 1`, `--modo llm --sin-rag` y
  `--modo reglas` (comparador, sin LLM).

### Apuntar a un clúster real

**Solo en un namespace dedicado a las pruebas.** Las fallas se inyectan de verdad: nunca en un
namespace con servicios en uso. El runner y los scripts se niegan si el namespace no está en
`EXP_NAMESPACES_PERMITIDOS`, y el runner además exige la etiqueta `aiops-experimento=true`.

1. Crear el namespace y desplegar los workloads del laboratorio:

   ```bash
   export EXP_NAMESPACE=aiops-pruebas EXP_NAMESPACES_PERMITIDOS=aiops-pruebas
   kubectl create namespace "$EXP_NAMESPACE"
   kubectl label namespace "$EXP_NAMESPACE" aiops-experimento=true
   sed "s/aiops-lab/$EXP_NAMESPACE/g" k8s-lab/workload-*.yaml k8s-lab/rbac-aiops.yaml \
     | kubectl apply -f -
   ```

   Los `NodePort` fijos de los manifiestos pueden chocar con los del clúster: revisarlos.
2. Que Prometheus entregue las métricas con las etiquetas que usan las consultas
   (`up{service="checkout"}`, `rabbitmq_queue_consumers{queue="worker"}`,
   `kube_pod_status_ready` con su `namespace`), que Loki reciba los logs y que Grafana tenga las
   5 reglas de alerta con el webhook hacia la API.
3. Desplegar API y worker con el entorno que imprime
   `python scripts/experimento.py --imprimir-entorno --modo llm` (repetirlo con `--modo reglas`
   para ese brazo). Incluye el aislamiento entre corridas y `AIOPS_PROM_NAMESPACE`.
4. Correr desde una máquina con `kubectl` apuntando a ese clúster:

   ```bash
   EXP_WORKER_EXTERNO=1 EXP_K8S_API=https://... EXP_PROMETHEUS=https://... \
   EXP_API=https://... EXP_GRAFANA=https://... AIOPS_API_TOKEN=... \
   python scripts/experimento.py --modo llm --via webhook --variantes --semilla 2026 \
     --categorias servicio_detenido,pod_fallido,cola_detenida --salida resultados/real.csv
   ```

`disco_lleno` y `certificado_por_vencer` inyectan con `docker compose`: no corren en un clúster
real tal como están. Quitarlas de `--categorias` cambia el denominador de la TRA y hay que
declararlo. Los workloads siguen siendo los del laboratorio: el entorno cambia, los servicios no.

## 4. Analizar

```bash
python -m scripts.analizar_experimento resultados/llm-n3.csv \
    --linea-base resultados/linea_base.csv
```

Imprime tablas Markdown por escenario, la Tabla 15 separando limpias y variantes, el MTTR
pareado y el contraste de H1–H3 con los criterios del §6.6 de la tesis. Si el CSV es de
`--modo script`, el reporte lo advierte.

Para las variantes:

```bash
# 1. Rúbrica fijada ANTES de las corridas: docs/rubrica-diagnostico.md (su hash va en el congelado)
# 2. Generar la plantilla y calificarla a mano
python -m scripts.analizar_experimento resultados/llm-n3.csv --plantilla-rubrica resultados/rubrica.csv
python -m scripts.analizar_experimento resultados/reglas.csv --plantilla-rubrica resultados/rubrica-reglas.csv
# 3. Unir las dos planillas en una y comparar agente contra regla
python -m scripts.analizar_experimento resultados/llm-n3.csv --linea-base resultados/linea_base.csv \\
    --regla resultados/reglas.csv --calificaciones resultados/rubrica.csv
```

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
5. [ ] Base de conocimiento: key de Gemini cargada desde la UI (proveedor Google) y
       `make aiops-ingest` (runbooks + `corpus/`). Sin esto `buscar_conocimiento` responde
       "no disponible" y el agente sigue sin RAG (se nota en la columna `fuentes_recuperadas`).
       Las corridas medidas usan solo `origen=repo` (`AISLAMIENTO`): los PDF subidos no
       entran. El brazo de comparación es `--sin-rag`; ambos se corren con el mismo modelo.
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
