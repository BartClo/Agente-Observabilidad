# Agente generalista: cualquier alerta, acciones por niveles y memoria — Diseño

> Estado: **propuesto, pendiente de revisión del autor**. Sub-proyecto D. Se construye en
> tres entregas independientes (§4, §5, §6); cada una tiene su plan y se puede detener
> después de cualquiera de ellas.

## 1. Problema

Hoy el agente solo "existe" para 5 categorías cableadas en `domain/aiops_core/catalogo.py`.
Una alerta con otro nombre se clasifica como *fuera del catálogo* y se escala sin
investigarla; y aun dentro del catálogo el agente es ciego fuera de lo que le dan las tools
(en `pod_fallido` no puede leer los eventos del pod y por eso duda). El autor pide un agente
en el sentido pleno: que reciba **cualquier alerta configurada**, **decida entre varias
opciones** y **aprenda de los eventos guardados**.

## 2. Decisiones ya tomadas (con el autor)

| Decisión | Elección |
|---|---|
| Autonomía | **Híbrida por niveles**: lo declarado lo hace solo; lo nuevo lo propone y un humano aprueba; lo de riesgo alto nunca es automático |
| Aprendizaje | Memoria de incidentes pasados + estadísticas de efectividad, **con promoción controlada por una persona** |
| Experimento de la tesis | Sigue midiendo las 5 categorías con el catálogo fijo; lo nuevo se evalúa aparte |

## 3. Invariantes de seguridad (no se negocian)

1. **El LLM nunca escribe comandos ni parámetros libres.** Las acciones salen de una lista
   cerrada de nombres con un único parámetro validado (`servicio`), como hoy.
2. **La política vive en código** (lista, kill switch, umbral de confianza, cortacircuito,
   reintentos, aprobación) y no lee ni la memoria ni las citas.
3. **La aprobación humana se registra en el dominio** (`Ciclo.aprobar`). Una acción
   propuesta no se ejecuta sin ella, aunque el LLM lo pida.
4. **Aprender no concede permisos.** Ninguna estadística ni registro pasado amplía la lista
   de acciones; solo puede *sugerir* a un administrador que lo haga.
5. **Las herramientas de investigación son de solo lectura** y acotadas al servicio del
   incidente por el sistema, no por el LLM.
6. **Todo lo que vuelve al LLM es dato no confiable**: saneado, delimitado y rotulado.

## 4. Entrega 1 — Entrada universal e investigación (solo lectura)

**Entrada universal.** `Ciclo.clasificar` deja de cortar con "fuera del catálogo". Una
alerta sin categoría recibe la categoría virtual `no_catalogada`: no remediable por sí
misma, sin runbook, pero **el incidente sigue** (hoy termina ahí). Para las 5 categorías
actuales nada cambia.

**Herramientas nuevas (solo lectura):**

| Tool | Qué hace | Acotado por el sistema |
|---|---|---|
| `consultar_metricas(incidente_id, promql)` | Consulta instantánea en Prometheus | Máx. 300 caracteres, timeout de 10 s, resultado truncado, 10 consultas por incidente, solo `query` (nunca escritura) |
| `consultar_eventos(incidente_id)` | Estado del pod/deployment del servicio: fase, condiciones, `lastState` de los contenedores, reinicios y eventos recientes | El namespace y el selector salen del incidente; el LLM no elige el objeto |

El resultado pasa por `sanear_linea` y se entrega delimitado como dato. Cierra el hueco
observado en `pod_fallido` (el agente no podía distinguir un ConfigMap erróneo de un fallo
transitorio). Requiere ampliar el RBAC del ServiceAccount con lectura de `pods` y `events`
(`get`, `list`); sigue sin poder escribir nada más de lo actual.

**Interruptor** `AIOPS_INVESTIGACION` (por defecto `1`), igual que `AIOPS_RAG`. Como cambia
el agente medido, **se revalida en vivo antes de congelar**.

## 5. Entrega 2 — Acciones por niveles y propuesta con aprobación

**Biblioteca de acciones ampliada** (`ACCIONES_PERMITIDAS`, cada una con `riesgo`):

| Acción | Efecto | Riesgo |
|---|---|---|
| `restart_service`, `recreate_pod`, `restart_consumer`, `compress_old_logs` | Las actuales | bajo |
| `scale_up_service` | +1 réplica del Deployment, con tope configurable | medio |
| `rollback_deployment` | Vuelve a la revisión anterior (`rollout undo`) | medio |
| cualquier otra (borrar datos, tocar configuración, secretos) | **No existen** | — |

**Catálogo declarativo** `agents/aiops/catalogo.yaml`: por alerta (y servicio opcional), su
señal sana (PromQL), las acciones permitidas y el rollback. Se valida al cargar contra
`ACCIONES_PERMITIDAS`; las 5 categorías actuales siguen siendo las incorporadas y una
colisión se rechaza. Su hash queda en `congelado.json`.

**Política por niveles:**

| Caso | Resultado |
|---|---|
| Acción declarada para esa alerta, riesgo bajo | Autónoma (como hoy) |
| Acción declarada, riesgo medio | Aprobación humana |
| Acción **no** declarada que el agente propone (de la biblioteca) | **Propuesta pendiente** con su diagnóstico; requiere aprobación |
| Riesgo alto o fuera de la biblioteca | Rechazada: escala |

**Cómo se ejecuta una propuesta sin reanudar el grafo del LLM** (hoy la reanudación no está
cableada): el agente registra `proponer_accion(incidente_id, accion, justificacion)` y
termina; el incidente queda `esperando_aprobacion`. Cuando una persona aprueba en la UI,
**el dominio ejecuta** (`Ciclo.ejecutar_propuesta`) pasando otra vez por la política
(kill switch, lista, cortacircuito), verifica y cierra. El LLM no participa en la ejecución.

**Verificación para alertas nuevas.** Si el catálogo declara una señal sana (PromQL), se
usa. Si no, la propia regla de Grafana: recuperado = la alerta vuelve a Normal y se
mantiene. Requiere un método nuevo en `ObservabilidadPort` (estado de la alerta) con su
adaptador de Grafana.

## 6. Entrega 3 — Memoria que aprende, con control humano

1. **Registro por incidente cerrado o escalado**, generado por plantilla (no por el LLM):
   alerta, servicio, diagnóstico, acciones, resultado verificado, MTTR y quién aprobó. Se
   indexa en el RAG con `origen=aprendido`, `tipo=incidente`, `servicios=[servicio]`.
2. **Efectividad.** Consulta sobre `aiops_incidentes` agrupada por (alerta, acción): intentos
   y recuperaciones **verificadas**. Tool `consultar_historial(incidente_id)` devuelve p. ej.
   "`restart_service` en `ServiceDown`/`checkout`: 4 de 5 verificadas".
3. **Promoción controlada.** `GET /catalogo/sugerencias` lista las acciones propuestas y
   aprobadas con ≥ 3 recuperaciones verificadas y ≥ 80 % de éxito. Una persona decide si las
   agrega al YAML. **Nunca se agregan solas.**

**Riesgos y mitigaciones.**
- *Bucle de refuerzo:* las estadísticas cuentan solo resultados verificados, no la confianza
  declarada por el LLM.
- *Envenenamiento* (provocar incidentes para sesgar las cifras): el historial es información,
  no entra en la política, y la promoción exige una persona.
- *Contaminación del experimento:* en las corridas medidas la memoria se desactiva
  (`AIOPS_MEMORIA=0` y `AIOPS_RAG_ORIGENES=repo`, ya en `AISLAMIENTO`); si no, el agente
  aprendería de sus propias corridas.

## 7. Impacto en la tesis y en el experimento

- **Núcleo medido intacto:** las 5 categorías, catálogo fijo, sin propuestas y sin memoria.
  H1–H3 se contrastan sobre eso.
- **Entrega 1 sí toca el agente medido** (tools de investigación). Se valida en vivo y luego
  se congela; la comparación con y sin investigación puede reportarse como brazo adicional.
- **Capacidad nueva, evaluada aparte** y de forma descriptiva: un conjunto pequeño de
  alertas no catalogadas (p. ej. latencia alta, un Deployment nuevo en crash-loop) con su
  resultado y el comportamiento de la propuesta/aprobación. No entra en la TRA.
- **Alcance a redactar con cuidado:** la tesis habla de incidentes recurrentes de nivel 1.
  Esto lo amplía; conviene presentar el núcleo N1 como lo medido y lo demás como capacidad
  adicional demostrada, no como un resultado.
- **El congelado se posterga** hasta cerrar la Entrega 1.

## 8. Pruebas

Dominio: alerta no catalogada continúa el incidente; propuesta no ejecuta sin aprobación;
`ejecutar_propuesta` respeta kill switch, lista y cortacircuito; acción fuera de la
biblioteca rechazada; riesgo medio exige aprobación; el YAML con una acción inexistente se
rechaza al cargar; la memoria no modifica la política. Herramientas: `consultar_metricas`
rechaza escrituras y consultas largas y respeta el tope; `consultar_eventos` no acepta
objeto elegido por el LLM; todo resultado sale saneado y delimitado. Un test de documento
hostil en el historial comprueba que la acción no cambia.

## 9. Fuera de alcance

Shell o `kubectl` libre; acciones de riesgo alto; modificar manifiestos o configuración;
promoción automática; entrenamiento o ajuste fino del modelo; gestión de varios clústeres.

## 10. Preguntas abiertas

- ¿Qué acciones de la biblioteca ampliada se quieren de verdad además de `scale_up_service`
  y `rollback_deployment`?
- ¿La aprobación de propuestas la hace cualquier operador o solo el administrador?
- ¿El adaptador de Grafana para el estado de la alerta se alcanza desde el worker con la
  misma URL del compose? (Hay que verificarlo; no está probado desde el contenedor.)
