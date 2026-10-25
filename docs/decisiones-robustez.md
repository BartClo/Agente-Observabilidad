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
