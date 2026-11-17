# Resultados del experimento: agente AIOps L1 con Claude Sonnet 5.5

Fecha: 2026-11-16 · Fase: **final** (agente congelado) · Laboratorio: k3d `aiops-lab` + Prometheus/Loki en Docker Compose

## 1. Configuración del agente evaluado

| Parámetro | Valor |
|---|---|
| Modelo | `anthropic:claude-sonnet-5-5` |
| Arquitectura | Agente único con tools (detectores, política, ejecutor y verificador como herramientas) |
| Umbral de confianza de la política | 0,80 |
| Investigación activa | Sí (`consultar_eventos`, `consultar_logs`) |
| RAG | Sí, solo documentos del repositorio (`origen=repo`) |
| Commit congelado | `73228bea2b3ebb04e9b69541c6f34816298b0125` |
| Hash del prompt (SHA-256) | `e8c2bb72…228e13d` |
| Hash de los runbooks (SHA-256) | `c414418a…0da6f` |
| Registro del congelamiento | `resultados/congelado.json` |

## 2. Diseño

- 5 categorías de falla inyectadas: `servicio_detenido`, `pod_fallido`, `cola_detenida`, `disco_lleno`, `certificado_por_vencer`.
- **Nivel 3 (autónomo):** 5 repeticiones por categoría, 25 corridas, intercaladas entre categorías.
- **Nivel 1 (control, solo recomienda):** 1 repetición de las 3 categorías remediables.
- Cada corrida deja el servicio sano, inyecta la falla, espera a que la anomalía sea visible en Prometheus (= disparo de la alerta), hace atender el incidente y lee el resultado de la API.
- La elegibilidad se define por la falla **inyectada**, no por la clasificación del agente, para que un error de clasificación no achique el denominador.
- Corridas excluidas por fallas de infraestructura: **0**.

## 3. Resultados por categoría (nivel 3)

| Categoría | n | Elegible | TRA | MTTR (prom.) | MTTR (mediana) | Precisión de clasificación | Acciones incorrectas | Tokens/incidente | Turnos LLM |
|---|---|---|---|---|---|---|---|---|---|
| servicio_detenido | 5 | sí | 100 % | 74,7 s | 30,1 s | 100 % | 0 % | 50.322 | 7,6 |
| pod_fallido | 5 | sí | 80 % | 25,9 s | 24,6 s | 100 % | 0 % | 46.435 | 7,0 |
| cola_detenida | 5 | sí | 100 % | 25,3 s | 26,0 s | 100 % | 0 % | 45.767 | 7,0 |
| disco_lleno | 5 | sí | 0 % | – | – | 100 % | 0 % | 42.123 | 6,8 |
| certificado_por_vencer | 5 | no | – | – | – | 100 % | 0 % | 32.961 | 5,4 |
| **Total** | **25** | | **70 %** | **43,1 s** | **28,4 s** | **100 %** | **0 %** | mediana 45.715 | |

- `disco_lleno` es elegible según el catálogo, pero no se puede remediar en este laboratorio (`compress_old_logs` no es una operación de Kubernetes). Se mantiene en el denominador, así que el techo de TRA con un agente perfecto era **75 %**.
- `certificado_por_vencer` no tiene acción autorizada y escaló por diseño las 5 veces.
- La única corrida elegible remediable que no se resolvió fue un `pod_fallido` con confianza 0,75 (< 0,80): la política denegó la acción y el agente **escaló sin actuar**.

## 4. Contraste de hipótesis

| Hipótesis | Criterio | Resultado | n | ¿Cumple? |
|---|---|---|---|---|
| **H1** TRA | ≥ 30 % | **70,0 %** (IC 95 % de Wilson: 48,1–85,5 %) | 20 elegibles | **Sí** |
| **H2** MTTR | −20 % vs. resolución manual | Agente: mediana 28,4 s | 14 resueltos | **Pendiente**: falta la línea base manual |
| **H3** Acciones incorrectas | ≤ línea base manual | Agente: **0 %** (0 de 25) | 25 | **Pendiente** de comparar con la línea base |

El límite inferior del intervalo de confianza de H1 (48,1 %) supera el criterio del 30 %. Con n = 20 se reporta como resultado de laboratorio, no como contraste estadístico formal.

## 5. Tiempos: de la alerta a la acción

Medidos sobre las 14 corridas resueltas, desde el disparo de la alerta, con los eventos de la línea de tiempo del incidente:

| Hito | Mediana | Mín. | Máx. |
|---|---|---|---|
| Abre el incidente | 1,2 s | 1,0 s | 4,7 s |
| Termina el diagnóstico | 15,3 s | 11,9 s | 25,6 s |
| **Ejecuta la acción** | **17,1 s** | 12,9 s | 53,3 s |
| Cierre verificado (MTTR) | 28,4 s | 19,6 s | 254,5 s |

- La investigación con el LLM (métricas, logs, eventos y RAG) ocupa unos 14 s. La decisión y la acción toman 1–2 s más.
- De la acción al cierre pasan unos 10 s: es la espera hasta verificar que el servicio volvió a estar sano.
- El máximo de 254,5 s corresponde a un `servicio_detenido` en el que el agente actuó a los 53 s y la verificación tardó cerca de 200 s más. Es atribuible a la carga del laboratorio (no verificado), y por eso se reporta la mediana además del promedio.
- El reloj arranca cuando la anomalía es visible en Prometheus. En un despliegue real se suma el retraso de Alertmanager (`for:` de la regla + `group_wait`), que es igual con y sin agente y no afecta a H2.

## 6. Control: nivel 1 (solo recomienda)

| Categoría | n | TRA | Precisión de clasificación | Acciones incorrectas | Tokens/incidente |
|---|---|---|---|---|---|
| servicio_detenido | 1 | 0 % | 100 % | 0 % | 40.318 |
| pod_fallido | 1 | 0 % | 100 % | 0 % | 40.811 |
| cola_detenida | 1 | 0 % | 100 % | 0 % | 45.050 |

Como se esperaba, con nivel 1 el agente clasifica y diagnostica correctamente pero no ejecuta acciones: la TRA es 0 %. La autonomía depende de la política y no del modelo.

## 7. Conocimiento (RAG) y costo

- Citas verificadas en **18 de 25** diagnósticos que recuperaron pasajes (72 %).
- Confianza declarada: mediana 0,80.
- Tokens por incidente: mediana 44.440 de entrada y 1.415 de salida.
- Total del experimento con nivel 3: 1.049.273 tokens de entrada y 38.766 de salida.

## 8. Ajustes previos al experimento (fase de ajuste)

Se hicieron con corridas de humo, **antes** de congelar el agente, y deben declararse:

1. **Calibración de la confianza en el prompt.** En las primeras corridas el agente clasificaba bien pero escalaba con confianza 0,50–0,75. El motivo era que trataba como evidencia **posibilidades** leídas en postmortems del RAG (p. ej. "en un incidente pasado recrear el pod no sirvió"). Se agregó una regla general: una condición de "Escalar si" del runbook cuenta solo si se **observó**. Si el runbook ya prevé qué hacer cuando la acción falla, esa condición se comprueba ejecutando y verificando.
2. **RB-003 (pod fallido).** La evidencia esperada pedía solo "reinicios crecientes". Se amplió para incluir el pod NotReady por readiness probe fallida (eventos `Unhealthy`), que es otra manifestación real de la misma categoría.
3. **Laboratorio.** Al recrear el clúster faltaban los puertos de `checkout` y del consumidor, y la recolección de logs de los pods hacia Loki (promtail). Sin logs, el agente no podía respaldar la evidencia esperada de RB-001 y RB-004.

Evolución en las corridas de humo (1 corrida por categoría): `pod_fallido` pasó de escalar con confianza 0,50 a resolverse con 0,80. Con los logs disponibles, `servicio_detenido` y `cola_detenida` se resolvieron con confianza 0,90 y 0,85.

## 8b. Versión final: confianza calculada por evidencia (commit `62b0599`)

Cambios respecto de la versión de las secciones 3 a 7:

- El LLM ya no elige un número de confianza. Declara si se cumple la evidencia esperada
  del runbook y qué condiciones de escalamiento observó, y el sistema calcula 0,9 o 0,5.
- Antes de llamar al LLM se ejecutan la confirmación, la clasificación, los logs y los
  eventos, y sus resultados se le entregan al modelo.
- Hay condiciones de escalamiento que el sistema detecta solo, sin el LLM: la recurrencia
  y las causas persistentes en los eventos.
- Que la consulta de logs venga vacía ya no cuenta como evidencia en contra.

| Categoría | TRA anterior | **TRA final** | MTTR anterior | **MTTR final** |
|---|---|---|---|---|
| servicio_detenido | 100 % | **100 %** | 74,7 s | **31,4 s** |
| pod_fallido | 80 % | **100 %** | 25,9 s | **26,3 s** |
| cola_detenida | 100 % | **100 %** | 25,3 s | **27,0 s** |
| disco_lleno | 0 % | 0 % | – | – |
| **Global** | 70 % (IC 48–86) | **75 % (IC 53–89)** | 43,1 s | **28,2 s** |

Otros resultados de la versión final:

- El costo bajó de ~46k a ~43k tokens por incidente, y los turnos del LLM de ~7 a 6.
- La confianza mediana fue 0,90.
- La clasificación fue correcta en el 100 % de los casos.
- En las tres categorías que el laboratorio puede ejecutar, el agente resolvió 15 de 15.

**Acciones incorrectas: 25 % (5 de 20 corridas con acción). Se informa sin ajustar.** Las
5 corresponden a `disco_lleno`. El agente eligió la acción que indica el runbook,
`compress_old_logs`, pero el backend de Kubernetes del laboratorio no la implementa:
el ejecutor la rechazó sin cambiar nada y el agente escaló. La métrica cuenta como
incorrecta toda acción intentada que no se verificó, y no se cambió después de ver los
datos. En la versión anterior esta tasa era 0 % porque el agente se abstenía cuando no
había logs.

**Corridas descartadas, por transparencia.** Dos corridas intermedias no forman parte
del resultado:

- `final-evidencia-n3`: TRA de 30 %.
- `final-evidencia-v2-n3`: detenida a mitad de camino.

Las dos fallaron por un error de implementación. El detector de recurrencia ("2
remediaciones del mismo servicio en la última hora") no respetaba el aislamiento del
experimento (`AIOPS_BREAKER_MAX=0`), y el experimento inyecta fallas en el mismo servicio
cada 4 o 5 minutos. A partir de la tercera repetición, todo quedaba con confianza 0,5.
Se corrigió en `62b0599`: el detector usa el mismo interruptor que el cortacircuito.

## 8c. Plataforma Docker (lo que usa AI Factory, commit `7914b2d`)

Mismo agente, mismo modelo y mismo diseño (nivel 3, 5 repeticiones, aislamiento entre corridas), pero sobre contenedores Docker locales (`ia-factory-lab-web/api/worker`) con el ejecutor del host (`docker restart` con lista de permitidos; el agente no toca `docker.sock`). Datos: `resultados/final-docker-n3.csv`.

| Escenario (alerta) | Categoría | n | Resuelto sin humano | MTTR medio |
|---|---|---|---|---|
| contenedor_detenido (ContainerStopped) | contenedor_fallido | 5 | 5/5 | 30,4 s |
| contenedor_unhealthy (ContainerUnhealthy) | contenedor_fallido | 5 | 5/5 | 34,0 s |
| servicio_sin_respuesta (ServiceDown) | servicio_caido | 5 | 5/5 | 25,0 s |
| **Total** | | 15 | **100 %** (IC 95 % Wilson 79,6–100 %) | **29,8 s** |

Precisión de clasificación 100 %, acciones incorrectas 0 %, ~38,6k tokens y 6 turnos LLM por incidente, confianza mediana 0,9.

Comparación con Kubernetes (sección 8b): en las categorías que la plataforma puede ejecutar ambas resuelven el 100 % con MTTR similar (28,2 s K8s, 29,8 s Docker). La diferencia de TRA global (75 % vs 100 %) viene de que el set K8s incluye `disco_lleno`, cuya acción no está implementada en ese backend.

Corridas descartadas: `descartada-docker-limite-n3` (60 %): las rondas 4 y 5 las rechazó el límite de 3 reinicios/hora del ejecutor del host, que se apagó para el experimento (`AIOPS_EJECUTOR_MAX_POR_HORA=100`). La corrida final se cortó tras 13 de 15 por falta de memoria del equipo; las 2 restantes se completaron después con el mismo commit congelado.

Línea base manual: aún no medida (H2 y H3 sin datos). El ejemplo de `resultados/DEMO-linea-base-simulada/` es ilustrativo y no es un resultado.

## 9. Limitaciones

- Laboratorio en una sola máquina compartida: la carga externa afecta el MTTR.
- Fallas inyectadas y conocidas, sin ruido de producción ni alertas espurias.
- `disco_lleno` no se puede remediar en el laboratorio y baja la TRA máxima a 75 %. En la versión final, además,
  suma 5 acciones intentadas y rechazadas por el ejecutor del laboratorio (ver 8b).
- El consumidor de `cola_detenida` es **simulado**: `restart_consumer` es real, el consumidor no.
- Corpus del RAG **sintético**, redactado para el laboratorio.
- n = 5 por categoría: los resultados se reportan con su n y su intervalo, sin p-valor.
- Un solo modelo evaluado (Claude Sonnet 5.5) en la fase final.

## 10. Pendiente

1. **Línea base manual** (≥ 3 corridas por categoría remediable) para contrastar H2 y H3:
   `python -m scripts.linea_base --categoria <cat> --operador <nombre> --salida resultados/linea_base.csv`
2. Volver a analizar con la línea base:
   `python -m scripts.analizar_experimento resultados/final-evidencia-v3-n3.csv --linea-base resultados/linea_base.csv`

## Datos crudos

- `resultados/final-evidencia-v3-n3.csv`: **versión final**, nivel 3, 25 corridas
- `resultados/final-evidencia-n3.csv`, `resultados/final-evidencia-v2-n3.csv`: corridas descartadas (ver 8b)
- `resultados/final-sonnet55-n3.csv`: nivel 3, 25 corridas
- `resultados/final-sonnet55-n1.csv`: control con nivel 1, 3 corridas
- `resultados/congelado.json`: versión exacta del agente evaluado
- `resultados/humo-sonnet55*.csv`: corridas de ajuste (no forman parte del resultado)
