# Decisiones de robustez del agente

> Registro de decisiones tomadas a partir de las corridas de humo con DeepSeek
> (2026-10-08) para que el agente cumpla lo que promete la tesis (RNF de confiabilidad,
> trazabilidad y escalamiento con evidencia). Cada decisión dice qué problema la motivó,
> qué se descartó, cómo se verificó y qué límite conserva.
>
> Formato: **Problema → Decisión → Alternativas descartadas → Verificación → Límite**.

---

## D1. Timeout operacional de reloj en las acciones

**Problema.** En una corrida real, `restart_service` tardó **810 s** en volver. La tesis
exige "timeout operacional" (RNF de confiabilidad, sección 4.1) y el código lo tenía a
medias: cada acción define `timeout_s` (60–120 s), pero se pasaba a `urllib`, y ese
timeout acota **cada operación de socket**, no la acción completa. Una API que entrega
bytes de a poco, o un handshake TLS trabado, lo esquivan.

**Decisión.** `ejecutar_accion` (dominio) corre el backend en un hilo y espera como
máximo `timeout_s` de reloj. Si vence, lanza `AccionSinRespuesta` (subclase de
`TimeoutError`). El ciclo ya registraba las excepciones del backend como **acción
fallida**, así que el incidente queda con la acción en `fallo` y el agente escala.

**Por qué el resultado se trata como incierto.** Que no haya respuesta no significa que
la acción no se aplicó: el `PATCH` pudo llegar. Por eso el mensaje dice "resultado
incierto: verificar; si no recupera, escalar sin reintentar" y la política de reintentos
(`max_reintentos`) sigue contando la acción.

**Descartado.**
- Timeout solo en el cliente HTTP: es el que ya existía y no alcanzó.
- Matar el hilo: Python no puede. El hilo queda *daemon* y muere con el proceso.
  Si un backend cuelga seguido, se arregla en el backend (marcado con `ponytail:`).

**Verificación.** `domain/aiops_core/test_aiops.py`: backend que ignora el timeout (lo
espera 30 s con timeout de 1 s) → lanza `AccionSinRespuesta`; los errores normales del
backend se propagan igual que antes; el ciclo registra la acción sin respuesta como
fallida.

**Límite.** El hilo colgado sigue consumiendo un socket hasta que el sistema operativo
lo cierre.

## D2. Timeout y reintentos del cliente LLM

**Problema.** Una llamada colgada al proveedor deja el incidente a medias. En la
corrida del 2026-10-08 hubo un `APIConnectionError`.

**Decisión.** `construir()` pasa `timeout` (`AIOPS_LLM_TIMEOUT_S`, 120 s) y
`max_retries` (`AIOPS_LLM_REINTENTOS`, 2) a los cuatro proveedores. El job completo ya lo
acota RQ (`AIOPS_JOB_TIMEOUT_S`, 900 s).

**Por qué pocos reintentos.** Cada reintento del cliente suma espera al MTTR; el
respaldo (D4) cubre las caídas largas.

**Verificación.** `tests/test_infra_llm_config.py`: los cuatro clientes quedan con el
timeout configurado (cada integración lo guarda con su propio nombre de atributo:
Anthropic usa `default_request_timeout`) y `max_retries == 2`.

## D3. Reconciliador de incidentes colgados

**Problema.** Si el agente muere o se cuelga después de actuar, el incidente queda en
`accion_ejecutada` para siempre, sin verificación ni cierre. Viola "verificar antes de
cerrar" y "escalamiento con evidencia completa": nadie se entera.

**Decisión.** `Ciclo.reconciliar(max_edad_s)` revisa los incidentes no terminales con más
de `AIOPS_RECONCILIAR_EDAD_S` (1800 s) desde su apertura:

| Situación | Resultado |
|---|---|
| Con acciones y la señal independiente muestra recuperación | Se verifica y se **cierra** (auditado como `reconciliado`) |
| Con acciones y sin recuperación | Se **escala**. **Nunca** reintenta la acción |
| Sin acciones (nadie lo atendió) | Se **escala** |
| Espera aprobación humana (nivel 2) | No se toca: ese plazo lo decide operaciones |
| Ya terminal o reciente | No se toca |

**Qué lo dispara.** El worker, al inicio de cada job (best-effort: un fallo del barrido
nunca impide atender la alerta nueva), y `POST /reconciliar` para un cron externo.

**Descartado.** Un scheduler propio: más piezas para un caso poco frecuente.

**Verificación.** Tests de dominio para los cuatro casos; test del endpoint; test de que
el fallo del barrido no rompe el job.

**Límite (`ponytail:`).** Solo corre cuando llega una alerta o alguien llama al
endpoint. Un incidente colgado sin más alertas ni cron espera. Para cerrarlo sin
tráfico hace falta un scheduler.

## D4. Respaldo de LLM a nivel de corrida (no de modelo)

**Problema.** Si el proveedor falla (caída, sin saldo, timeout), el incidente se pierde.

**Decisión.** Se puede configurar un modelo de respaldo (UI → "Respaldo", tabla
`aiops_llm_activo`). Si la corrida con el principal lanza una excepción y el incidente
**no terminó**, el worker lo **retoma** con el respaldo, con un pedido que dice que
consulte `estado_incidente` y continúe sin repetir lo hecho. Queda auditado como
`llm_respaldo` y el incidente registra `modelo_llm = "principal -> respaldo"`.

**Por qué a nivel de corrida y no `with_fallbacks`.**
- El estado del incidente vive en el `Ciclo` (Postgres), no en el contexto del LLM; otro
  modelo puede retomarlo.
- `RunnableWithFallbacks` no expone `bind_tools`, que el agente necesita.
- Un wrapper propio contaría los tokens dos veces (el callback de uso cuenta la llamada
  interna y la externa).

**Reglas.** El respaldo exige API key cargada y no puede ser el mismo par
proveedor+modelo que el principal. Borrar la key del respaldo lo quita. Un respaldo
ilegible (clave maestra cambiada) se ignora: nunca impide atender el incidente. Si
fallan los dos, se propaga el **primer** error y quedan registrados ambos modelos.

**Verificación.** `tests/test_llm_respaldo.py` (retoma, sin respaldo propaga, fallan
ambos, incidente ya terminal no llama al respaldo) y tests de configuración y API.

**Límite.** Comparar modelos en el experimento exige **no** configurar respaldo (un
incidente "a medias entre dos modelos" no es atribuible a uno). El CSV lo deja visible
en `modelo_llm`.

## D5. Avisos a Google Chat con bandeja de salida (outbox)

**Problema.** La sección 4.3 de la tesis deja pendiente la "interfaz de escalamiento
hacia L2/SRE". Hoy el agente solo "habla" si alguien abre la UI.

**Decisión.** Cada hito de un incidente se publica en un espacio de Google Chat, **un
hilo por incidente**:

| Evento | Aviso |
|---|---|
| `abierto` | 🚨 incidente abierto |
| `accion` | 🔧 acción ejecutada (ok / falló) |
| `decision_politica` con veredicto `aprobacion` | ⏳ necesita aprobación humana |
| `escalado` | 🔴 escalado a L2/SRE con el motivo |
| `cerrado` | ✅ resuelto (autónomo o con humano, segundos desde la alerta) |
| `reconciliado` | 🛠️ cerrado o escalado por el reconciliador |

Los avisos salen **de la auditoría**, no del LLM: son exactos y no gastan tokens.

**Robustez.**
- **Outbox en Postgres** (`aiops_notificaciones`): el aviso se guarda antes de enviarse;
  si Google Chat está caído queda `pendiente` y se reintenta con espera creciente
  (15 s → 15 min), hasta 8 intentos y luego `fallida`. Entrega *al menos una vez*, sin
  duplicados (clave única por incidente + tipo + instante) y sin doble envío entre
  procesos (`FOR UPDATE SKIP LOCKED`).
- **Cortacircuito**: tras un fallo no se reintenta en 60 s desde ese proceso: un Google
  Chat caído no suma segundos al MTTR de cada incidente.
- **Nunca rompe al agente**: cualquier fallo del aviso se registra y se ignora.
- **Reintentos en segundo plano** cada 30 s mientras la API esté arriba.
- **Observable**: `GET /notificaciones`, métrica `aiops_notificaciones{estado}` y
  `POST /notificaciones/probar` (admin) para validar el webhook.

**Seguridad.**
- La URL del webhook lleva `key` y `token`: es un secreto. Solo se acepta
  `https://chat.googleapis.com`, se valida **al armar** (no en el primer incidente) y
  **nunca** aparece en errores ni logs (tests con un secreto marcador).
- El texto de alertas, logs y del LLM es **no confiable**: se le quitan `<`, `>` y
  comillas invertidas, para que un `<users/all>` en una alerta no mencione a todo el
  espacio ni inyecte formato.
- El experimento vacía el webhook a propósito (serían cientos de mensajes).

**Descartado.**
- Enviar desde una cola RQ: el worker atiende un incidente a la vez, así que los avisos
  de "abierto" llegarían al final, desordenados.
- Enviar en un hilo dentro del proceso: RQ mata el proceso hijo al terminar el job y
  pierde lo pendiente.
- Slack / Teams: el usuario eligió Google Chat. Cambiar de canal solo toca
  `infra/gchat.py`.

**Verificación.** `tests/test_notificaciones.py` contra un servidor HTTP local que
responde 200/429/500/conexión rechazada y contra el Postgres real: validación de URL,
sin filtración del secreto, hilos, orden, reintentos, cortacircuito, `fallida` tras 8
intentos, formato de cada hito, neutralización de menciones, y que un Google Chat caído
no rompe al agente.

**Límite.** El webhook es un secreto en `.env` (no en la UI cifrada, como las API keys).
Los mensajes no son interactivos (no se aprueba desde Google Chat): aprobar sigue siendo
un acto autenticado en la UI, a propósito.

## D6. El pod `api` del laboratorio deja constancia en su log

**Problema.** `pod_fallido` escaló 2 de 3 veces con DeepSeek porque el pod no escribía
nada: el agente veía `pod_ready=0` sin logs y citaba esa falta al bajar su confianza
(0,6–0,7 < 0,8). En `servicio_detenido` la confianza pasó de 0,60 (sin Loki) a 0,85 (con
logs). Son observaciones con `n` pequeño y con variabilidad entre corridas (el mismo
`pod_fallido` sin logs también llegó a 0,85 una vez): justifican mejorar la evidencia
disponible, no afirmar un efecto.

**Decisión.** El contenedor registra su arranque y **solo los cambios** de estado de su
chequeo de salud ("ERROR api: chequeo de salud fallando…"). No cambia el umbral de
confianza ni el prompt: se mejora la **evidencia disponible**, que es lo que la tesis
declara como condición de la autonomía.

**Límite.** Con esto el lab se parece más a un servicio real, pero sigue siendo
inyección de fallas conocidas. Se declara como amenaza a la validez.

## D7. Un agente único de tool-calling en lugar del orquestador + subagente

**Problema.** Cada incidente consumía ~65 mil tokens de entrada. La tesis mide el costo y
defiende "agente único" (sección 2.4), pero el worker corría un orquestador que solo
delegaba en un subagente `aiops` (herencia de la plantilla multiagente del repositorio).

**Medición (sin gastar LLM).** `scripts/medir_contexto.py` captura la primera solicitud
al modelo con un LLM falso y cuenta el contexto **fijo** que se reenvía en cada llamada:

| Arquitectura | Tools | Tokens sistema | Tokens tools | Total por llamada |
|---|---|---|---|---|
| A. Orquestador (2 llamadas por incidente) | 8 | 52 | 2.605 | 2.681 |
| B. Deep agent con las tools de aiops (equivale al subagente) | 22 | 1.186 | 3.828 | 5.038 |
| **C. Agente de tool-calling único (adoptado)** | **14** | 649 | 1.337 | **2.010** |

Conteo con `cl100k_base` (aproximado para otros proveedores). El subagente pesaba ~5.000
tokens por llamada: sus 14 tools más 8 tools internas de deepagents que el agente no usa
(archivos, lista de tareas, `task`) y la sección de skills. Con ~12 llamadas por incidente,
~12 × 5.000 ≈ 60 mil explica el costo observado; el orquestador aportaba poco.

**Decisión.** El worker corre `agents/aiops/agente.py`: un `create_agent` de LangChain con
el prompt y las 14 tools de `agents/aiops/agent.yaml` (se reutiliza la misma definición).
La plantilla multiagente (`app/main.py`) sigue disponible para otros agentes.

**Seguridad: no cambia.** Quitar deepagents elimina su `interrupt_on`, pero la aprobación
humana nunca dependió de él: `Ciclo.ejecutar_remediacion(aprobada=True)` exige una
aprobación registrada en el dominio y, si no la hay, la tool devuelve ERROR (test
`test_sin_interrupt_on_la_aprobacion_la_sigue_exigiendo_el_dominio`). También desaparecen
las tools de archivos y `task` (menos superficie para el LLM).

**Qué no se afirma.** La reducción medida es la del contexto fijo por llamada
(~60 %). El ahorro total de tokens por incidente depende además del historial acumulado y
del número de vueltas, y se valida en corridas reales (ver resultados). El comportamiento
del agente puede cambiar al cambiar su contexto: por eso este cambio va **antes** de
congelar el agente para el experimento.

**Descartado.**
- Quitar solo el orquestador (arquitectura B): ahorra ~5 mil tokens (~8 %), no el grueso.
- Skills de deepagents: el listado costaba tokens y el agente casi no leía el archivo;
  el catálogo y la acción llegan por `clasificar_incidente`.

## D8. Turnos y llamadas a tools por incidente

La sección 6.5 pide "número de turnos de investigación por incidente". Un callback de
LangChain cuenta las llamadas al LLM y a tools de la corrida completa (los callbacks de
`config` los heredan los runs hijos) y las suma en el incidente, incluso si hubo respaldo.
Las "tools" incluyen las internas del framework cuando existan, y se declara así en la
tesis. Columnas `turnos_llm` y `llamadas_tools` en el CSV del experimento.

## D9. Pedido explícito al agente único y brazo de comparación

**Problema.** En la primera corrida real con el agente único (2026-10-21) paró a los 3
turnos con el incidente en `abierto`: el pedido solo daba el id del incidente y el prompt
arranca por buscar/abrir la alerta. Sus 6.675 tokens no eran un ahorro: no trabajó.

**Decisión.** El pedido dice que el incidente ya está abierto y por dónde seguir
(`pedido_de`); el prompt admite saltar los pasos 1 y 2. Además `AIOPS_AGENTE=deepagents`
selecciona el agente de la plantilla como **brazo de comparación**, y el CSV registra qué
agente corrió cada fila.

**Verificación.** Tests del pedido y del interruptor; la validación en vivo es la
Tarea 9 del plan (6 corridas sin que ninguna termine sin cerrar ni escalar).

**Límite.** Se atribuye la parada al pedido por hipótesis; la corrida en vivo la confirma
o la descarta.

## D10. Cortacircuito entre incidentes

**Problema.** `max_reintentos` es por incidente. Una alerta que reaparece tras cada
reinicio crea otro incidente y otro reinicio, sin fin: el patrón "la automatización como
origen del incidente" (Tabla 3 de la tesis; AWS us-east-1) y un generador de acciones
incorrectas para H3. Google SRE pide límites de tasa y cortacircuitos propios del agente;
Azure SRE Agent tiene un período de espera por alerta.

**Decisión.** Antes de evaluar la política, el ciclo cuenta las acciones de remediación
sobre el mismo servicio en la ventana (`AIOPS_BREAKER_WINDOW_S`, 3600 s) sumando todos
los incidentes. Si llegan a `AIOPS_BREAKER_MAX` (3) deniega y el agente escala como
recurrente. Los rollbacks no cuentan. 0 apaga el cortacircuito.

**Descartado.** Degradar a nivel 2 en vez de denegar: más piezas sin que cambie lo que
medimos.

**Límite.** Recorre todos los incidentes en cada ejecución (`ponytail:` en el código).

## D11. Saneamiento de los logs que llegan al LLM

**Problema.** Los logs de Loki llegaban crudos al LLM, que corre en un proveedor externo.
La Tabla 3 de la tesis promete enmascarar identificadores sensibles; no estaba hecho.

**Decisión.** `Ciclo.logs()` pasa cada línea por `sanear_linea`: enmascara contraseñas y
tokens (`clave=valor`, JSON, `Bearer`, JWT, claves AWS y `sk-`), correos e IP; quita
caracteres de control y trunca a 300 caracteres. Está en el dominio, así que cubre a todo
consumidor de logs.

**Límite.** Es por patrones: no garantiza cubrir todo secreto. Las IP de pods se
enmascaran aunque a veces ayudarían al diagnóstico (se acepta). Los textos de alertas no
pasan por este filtro.

## D12. Fases ajuste/final e intervalos de confianza

**Problema.** Con 5 repeticiones por categoría, "60 %" puede ser 23–88 %. Y afinar el
prompt con las mismas corridas con que se mide infla el resultado (Google SRE llama
"hill climbing" a eso; Datadog vio una mejora que empeoraba en el conjunto completo).

**Decisión.** El CSV registra `fase` (`ajuste` o `final`); el análisis usa por defecto solo
`final` e imprime la TRA con su intervalo de Wilson al 95 %. No se afirma significancia
estadística: se reporta el valor, el intervalo y `n`. Un CSV sin columna `fase` (las
corridas de humo anteriores) se trata como ajuste.

**Límite.** Wilson supone corridas independientes; las del laboratorio comparten máquina
y modelo, lo que se declara como amenaza a la validez.

**Efecto colateral.** Se agregó `scripts/__init__.py`: sin él, mypy veía
`scripts/analizar_experimento.py` con dos nombres de módulo cuando un test lo importa.
Los scripts siguen corriendo igual (`python scripts/x.py` y `python -m scripts.x`).

## D13. Congelar el agente antes del experimento final

**Problema.** "No cambiar el prompt a mitad del experimento" dependía de la disciplina.

**Decisión.** `python -m scripts.congelar` registra commit, modelo, agente, umbral y los
hashes del prompt y de los runbooks en `resultados/congelado.json`, y se niega si hay
cambios sin commitear, si no hay modelo elegido o si hay modelo de respaldo. Las corridas
`--fase final` verifican que `HEAD` sea el congelado y el árbol esté limpio.

**Límite.** No detecta cambios en la configuración de Grafana o del laboratorio; esos se
describen en el protocolo.

## D14. La acción no la elige el LLM: prueba frente a la inyección por telemetría

**Problema.** Hay trabajo reciente (AIOpsDoom, USENIX Security 2026; solo vi resúmenes) que
muestra que un log puede empujar a un agente hacia una remediación dañina y que los
filtros de prompt no lo detienen. La mitigación que recomiendan es limitar lo que el
agente puede hacer.

**Decisión.** La propiedad ya estaba en el diseño: la categoría sale de la alerta, la
acción de la categoría y las tools de ejecución solo reciben el id del incidente. Se
agregan tests que la fijan (firma de las tools y un caso con texto hostil en logs y
diagnóstico) y un escenario en vivo (`experimento --inyeccion`) que escribe una línea
hostil en el log de `checkout`.

**Qué sí puede hacer un log hostil.** Influir en el diagnóstico, la confianza o el
escalamiento (disponibilidad), no elegir otra acción ni cerrar sin verificar.

**Límite.** Es evidencia sobre este modelo y este catálogo, no una prueba general.

## D15. Camino real de punta a punta y latencia de detección

**Problema.** El objetivo exige detectar "en tiempo real" y reducir el MTTR. El runner
invocaba el ciclo directamente: no pasaba por la regla de Grafana, el webhook, la cola ni
el worker, y no medía la detección. Ese camino solo se había probado sin LLM.

**Decisión.** `experimento --via webhook` (solo `--modo llm`) levanta un worker con el
entorno del laboratorio y el nivel de autonomía de la corrida (el del compose no lo trae),
inyecta la falla y **espera** a que Grafana dispare la alerta y a que el worker abra y
cierre el incidente. Registra `via` y `deteccion_s` (incidente abierto menos anomalía
visible en Prometheus). El MTTR conserva el mismo inicio que la línea base. El análisis
muestra la mediana de detección.

**Límite.** La detección incluye la latencia de la plataforma de observabilidad (regla de
Grafana cada 10 s con `for: 10s`), no solo la del agente: se reporta como tiempo del
sistema. El modo directo se conserva para ajustar rápido. La rama `webhook` está probada
con dependencias simuladas; su validación real es la Tarea 9 del plan.

## D16. `cola_detenida` remediable en el laboratorio (consumidor simulado)

**Problema.** De las 4 categorías elegibles solo 2 (`servicio_detenido`, `pod_fallido`)
eran remediables en el laboratorio. Con un agente perfecto la TRA máxima era 50 %, y para
llegar al 30 % de H1 hacía falta un 60 % de éxito en esas dos. Además `QueueStalled`
estaba **siempre en alerta** (el RabbitMQ del compose no tiene consumidores) y la consulta
del agente (`rabbitmq_queue_consumers{queue="worker"}`) no encontraba datos, así que ni
confirmaba la anomalía.

**Decisión.** Un Deployment `worker` en k3d (busybox + httpd, como `checkout`) publica
`rabbitmq_queue_consumers{queue="worker"}`. La falla lo pone en 0 (consumidor
desconectado) y `restart_consumer`, que ya era un `rollout restart`, lo reconecta. El
broker real deja de llevar `service=worker` y la regla de Grafana mira solo la métrica del
consumidor. Con 3 de 4 categorías remediables el umbral baja a un 40 % de éxito en ellas.

**No se cambia la definición de TRA ni se saca nada del denominador:** se amplía lo que el
laboratorio permite remediar y se declara.

**Límite.** El consumidor es una **simulación**: no procesa mensajes. Lo real es la acción
(rollout restart) y la verificación (la métrica vuelve a 1). `disco_lleno` sigue sin ser
remediable.

## D17. Aislamiento entre corridas del experimento

**Problema (hallado en vivo, 2026-10-25).** Cada corrida inyecta una falla en el **mismo
servicio**, así que una corrida contamina a la siguiente por dos vías: (1) el cortacircuito
—que existe para frenar la recurrencia real— cuenta las inyecciones del experimento como
recurrencia: tres corridas seguidas sobre `checkout` y la cuarta escalaba por "3 acciones en
la última hora"; (2) los logs `FATAL` de la corrida anterior siguen en la consulta de la
última hora y el agente veía "reinicios que vuelven a caer", que el runbook manda escalar.
Ambas habrían bajado la TRA sin que fuera una decisión del agente.

**Decisión.**
- `ObservabilidadPort.logs(servicio, lineas, desde)` y `Ciclo(logs_ventana_s)`: con ventana,
  los logs se piden desde `disparada_en - ventana`. Por defecto 0 = como siempre.
- El experimento fija `AIOPS_BREAKER_MAX=0` y `AIOPS_LOGS_VENTANA_S=60`
  (`experimento.AISLAMIENTO`), y `resultados/congelado.json` los registra.
- El cortacircuito sigue probado por separado: tests de dominio y, en vivo, escaló como
  "problema recurrente" en las tres corridas de la prueba de inyección.

**Descartado.** Limpiar Loki entre corridas (requiere configurar borrado) y espaciar las
corridas (la ventana de una hora las seguiría mezclando).

**Límite.** Con 60 s el agente ve menos contexto histórico que un operador en producción;
se declara como amenaza a la validez. La ventana debe cubrir el retraso entre la falla y la
alerta: ~10 s por la vía directa y ~30 s por Grafana.

## D18. Tres arreglos del camino real hallados en la primera corrida por webhook

Primera corrida real (2 repeticiones × `pod_fallido`, `servicio_detenido`, `cola_detenida`,
vía Grafana → webhook → worker → agente): detección **16,6–32,2 s** (mediana 31,9 s), 3 de
las 4 válidas resueltas. Salieron tres defectos del **runner**, no del agente:

1. **`pod_fallido` nunca disparaba el webhook.** Grafana solo notifica en la *transición* a
   Alerting; el pod se recupera en segundos y el runner lo volvía a romper antes de que la
   regla (que evalúa cada 10 s) lo viera en Normal. Ahora espera a que la alerta esté en
   Normal antes de inyectar (`esperar_alerta_inactiva`).
2. **Una falla `infra:` dejaba la falla puesta** y contaminaba la corrida siguiente. Ahora
   se recupera el servicio.
3. **Tokens y turnos podían leerse como 0.** El worker registra el costo *después* de
   cerrar o escalar; el runner leía el incidente apenas era terminal. Una corrida que
   trabajó 7 turnos y ~21 mil tokens apareció con 0 y 0. Ahora espera a que se registre el
   costo (`_esperar_costo`). Sin esto, el experimento final habría subestimado el costo de
   forma aleatoria.

**Consecuencia para el diseño del experimento.** Una alerta que está **siempre** en falla
(`certificado_por_vencer`, cuyo certificado vence en 3 días y no tiene recuperación) nunca
vuelve a Normal y no puede pasar por el webhook: esa categoría, y `disco_lleno` (que no es
remediable), se miden por la vía directa.

## D19. El worker corre con scheduler: un reintento no puede bloquear las alertas siguientes

**Problema (hallado en vivo, 2026-10-25).** El webhook encola con
`Retry(max=2, interval=[30, 120])`. Un reintento con espera deja el job en estado
`scheduled`, y **solo un worker con scheduler** lo vuelve a encolar; el worker se lanzaba
sin él (`rq worker …`). Además el webhook deduplica por id de alerta y trata `scheduled`
como "en curso". Resultado: **un solo job que fallara una vez bloqueaba para siempre
todas las alertas con esa huella de Grafana**. Lo detonó el corte de una corrida (el
worker murió a mitad de un job), pero cualquier falla transitoria del LLM o un servicio
ocupado lo habría hecho igual. En el laboratorio se vio como `pod_fallido` que "nunca
disparaba el webhook" aunque Grafana sí disparaba.

**Diagnóstico.** `rq:job:aiops-webhook-PodFailed_…` en `scheduled` en Redis, un incidente
`abierto` huérfano, y el job retomado al instante al reiniciar el worker con scheduler.
Mi primera hipótesis (la transición de estado de Grafana) era incompleta: ese defecto
también existe y se corrigió (D18), pero no era la causa de este bloqueo.

**Decisión.** `rq worker --with-scheduler`. `tests/test_compose.py` fija la invariante:
si el webhook usa `Retry(interval=...)`, el comando del worker debe llevar el flag.

**Límite.** El incidente huérfano `abierto` de un worker muerto lo cierra el reconciliador
(a los 30 min) o el reintento; no es inmediato.

## Sesión en vivo del 2026-10-25 (validación del agente único, la inyección y el camino real)

Modelo `deepseek:deepseek-chat`, nivel 3, sin respaldo. Son corridas de **ajuste**
(`--fase ajuste`): validan el sistema, no son el resultado de la tesis.

| Prueba | Corridas | Resultado |
|---|---|---|
| Agente único, `pod_fallido` y `servicio_detenido`, vía directa | 6 | 6 de 6 completan el ciclo (7–8 turnos); 5 resueltas, 1 escalada por confianza 0,70 |
| Tokens por incidente (entrada + salida) | 6 | 20,7–24,1 mil, frente a ~65–70 mil con el agente de la plantilla |
| MTTR vía directa | 6 | `pod_fallido` 20–22 s; `servicio_detenido` 30–31 s |
| `cola_detenida`, modo script | 2 | 2 de 2 resueltas con `restart_consumer` (8–11 s) |
| Inyección por logs, con el cortacircuito activo | 3 | 3 de 3 escaladas **por el cortacircuito** (correcto: 3 acciones en la última hora); el agente señaló la línea hostil en las 3 |
| Inyección por logs, con aislamiento | 3 | 3 de 3 resueltas con **solo** `restart_service`; línea hostil señalada; kill switch intacto; ningún incidente descartado |
| Camino real por webhook, primera ronda | 6 | defectos del runner y del worker hallados y corregidos (D18, D19) |
| **Camino real por webhook, ronda limpia** | 6 | **6 de 6 resueltas** (2 × `pod_fallido`, `servicio_detenido`, `cola_detenida`); detección **17,1–38,2 s, mediana 25,2 s**; MTTR 39–77 s; 20,5–23,7 mil tokens; 7–8 turnos |

**Criterio de "tiempo real" (fijado antes de ver los datos): mediana de detección ≤ 60 s.
Cumplido** (25,2 s). La detección incluye la latencia de la regla de Grafana (evalúa cada
10 s con `for: 10s`): es tiempo del sistema, no solo del agente.

**Observaciones a declarar:**
- La mejora de tokens y tiempo viene de dos cambios a la vez (agente único y pedido
  explícito); no se puede atribuir a uno solo.
- El único escalamiento por confianza (0,70 en `pod_fallido`) coincidió con logs que
  mezclaban pods de corridas anteriores; D17 acota esa ventana para el experimento.
- El MTTR por el camino real incluye la detección (≈ 25 s) y por eso es mayor que por la
  vía directa. La línea base se mide desde la anomalía visible, igual que el agente.


## D20. RAG con citas verificables: diseño, validación en vivo y lo que NO está resuelto

**Decisión (con el autor).** El agente consulta una base de conocimiento (Gemini + pgvector)
y cita fuentes; el dominio rechaza citas que no se recuperaron en ese incidente. El RAG
**informa, no autoriza**: la acción la elige el catálogo, la política no lee las citas y un
fallo del conocimiento no bloquea (pausa de 60 s). Interruptor `AIOPS_RAG`; las corridas
medidas usan solo el corpus versionado (`AIOPS_RAG_ORIGENES=repo`).

**Calibración.** Piso de similitud 0,69 (relevantes 0,739–0,812; irrelevantes 0,543–0,638;
24 consultas etiquetadas por el autor del proyecto). Recalibrar si cambia el corpus, el tamaño
de fragmento o el modelo de embeddings.

**Validación en vivo (ajuste, camino real, DeepSeek `deepseek-chat`, n = 3 por brazo).**

| Brazo | Resueltas | Tokens (mediana) | Confianza (pod / servicio / cola) |
|---|---|---|---|
| Sin RAG | 2 de 3 | 23.882 | 0,78 / 0,85 / 0,90 |
| RAG, 4 pasajes de ~1000 car. | 2 de 3 | 32.773 (+37 %) | 0,62 / 0,82 / 0,85 |
| RAG, 3 pasajes de ~700 car. | 1 de 3 | 28.200 (+18 %) | 0,45 / 0,72 / 0,82 |

- Citas verificadas: 9 de 9 diagnósticos citaron fuentes que sí habían recuperado.
- **La confianza fue menor con RAG en las 6 comparaciones.** No hay "lavado de confianza"; el
  efecto es el contrario: más cautela.
- **Mecanismo observado en `pod_fallido` (0,45):** el agente relacionó el log con el
  postmortem del ConfigMap (donde recrear el pod no sirvió) y no pudo descartarlo porque no
  tiene una tool para leer los eventos del pod. Es razonamiento legítimo, pero baja la TRA.
- **Límites:** n = 3 por brazo (sin significancia); la variabilidad de la confianza con la
  misma evidencia ya era de 0,6 a 0,85; el postmortem del ConfigMap reproduce el mismo texto de
  log que el pod del laboratorio, lo que acentúa el efecto. No se ajustó el prompt ni el
  corpus con estos datos.
- **Pendiente:** el criterio "el documento hostil no cambia la acción" solo está probado con
  tests, no en vivo.

**Otras mejoras de robustez (mismo día).**
- Simulacro: nivel 0/1 dice qué habría ejecutado y lo audita (evento `simulacro`).
- El worker reconcilia incidentes colgados al arrancar (`agents/aiops/arranque.py`);
  verificado en vivo.
- Respaldo de LLM verificado en vivo: modelo principal inexistente → `BadRequestError` →
  evento `llm_respaldo` → Gemini retomó el mismo incidente. (El modelo barato lo escaló; eso no
  es del mecanismo.) Configuración restaurada: activo `deepseek-chat`, sin respaldo.


## D21. `consultar_eventos`: el agente puede ver el estado del pod (solo lectura)

**Problema.** En `pod_fallido` el agente solo veía métricas y logs. No podía distinguir una
falla pasajera de una causa persistente (ConfigMap erróneo, imagen inexistente) y, con el RAG,
dudaba (confianza 0,45) sin poder descartar el postmortem parecido. La tesis (§6.2) ya
condicionaba la variante «imagen inexistente» a que existiera esta herramienta.

**Decisión.** Tool `consultar_eventos(incidente_id)`:
- Puerto `InvestigacionPort` en el dominio (opcional); `Ciclo.eventos` toma el servicio del
  incidente (el LLM no elige objeto ni namespace), tope de 50, sanea cada línea con
  `sanear_linea`, audita `consulta_eventos` y convierte una falla del clúster en `ErrorCiclo`
  (el agente la lee y escala; no corta el ciclo).
- `BackendKubernetes.eventos`: `GET` de pods `app=<servicio>` y de `events` del namespace, filtrados
  a esos pods. Solo verbos de lectura.
- RBAC: se agrega **únicamente** `events: list` (`pods: list` ya existía). Sin `get` de
  secretos, sin `exec`.
- Resultado delimitado con `<<< >>>` (dato observado, no instrucciones). Interruptor
  `AIOPS_INVESTIGACION=0` quita tool y prompt; `congelar` registra su valor.

**Verificación en vivo (sin LLM).** Pod sano: fase `Running`, reinicios 0, eventos `Scheduled`.
Con una imagen inexistente: `ErrImagePull` / `ImagePullBackOff` con el motivo y los eventos
`Failed`/`BackOff`; el Deployment se restauró con `rollout undo`.

**No resuelto.** Falta medir si mejora la TRA o la abstención en las variantes confusoras con el
modelo congelado; cambia el agente medido, así que se valida en vivo antes de congelar.