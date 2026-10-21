# Textos para alinear la tesis con el agente implementado

> Texto listo para pegar en `Tesis_Agente_AIOps_USS.pdf`, sección por sección, escrito
> en el registro del documento. Cada bloque dice **qué sección reemplaza** y **qué
> hecho del repositorio lo respalda**, para que puedas verificarlo antes de pegarlo.
>
> Estado de referencia: commit del repositorio al 2026-10-21. Las cifras de resultados
> son de **pruebas de humo** (1–3 corridas), no del experimento: se marcan como tales y
> no deben presentarse como evidencia de H1–H3.
>
> Marcadores: `[COMPLETAR]` = dato que depende de ti o del experimento.

---

## 1. Decisiones de alcance que hay que reflejar

| Documento actual | Qué pasó | Qué hacer en el texto |
|---|---|---|
| RF5 y 4.2: RAG sobre runbooks | El runbook se obtiene **por identificador desde el catálogo**, no por búsqueda semántica | Reescribir (secciones 3 y 4 de este archivo) |
| RF2 y objetivo 3: "trazas" | No hay trazas distribuidas; ninguna categoría L1 las requiere | Quitar "trazas" de RF2 y del objetivo específico 3 |
| RNF "Integridad de herramientas": lista blanca de servidores MCP y hash | El agente **no usa servidores MCP**: sus tools son código propio versionado | Reescribir el requisito (sección 5) |
| 4.4: servidor MCP de Grafana, Datadog | No se usaron | Quitarlos de la lista de opciones o marcarlos como alternativas no adoptadas |
| RF12: modo revisión (nivel 2) | Funciona con aprobación humana en la UI, pero **no se evalúa con el LLM** | Declararlo como limitación (sección 9) |
| 6.5: SLA, precisión y recall de detección | Las fallas se inyectan; no hay SLA ni falsos positivos reales | Quitar esas métricas (sección 8) |
| 6.2: "proceso bloqueado", "saturación conocida" | No están en el catálogo implementado | Dejar los cinco casos del catálogo |

---

## 2. Capítulo 4.1 — Arquitectura (reemplaza el párrafo de la Tabla 5 y agrega la implementación)

> La Tabla 5 describe componentes lógicos. En el prototipo, esos componentes se
> materializan de la siguiente forma. El agente es **un único agente de tool-calling**
> (LangChain) que invoca catorce herramientas del ciclo L1; no existe un orquestador ni
> subagentes. Las herramientas son funciones delgadas: la lógica de decisión
> (clasificación, política, ejecución, verificación, rollback y escalamiento) reside en un
> **dominio de Python puro**, sin dependencias de frameworks de IA, que el agente invoca
> pero no puede eludir.

| Componente (Tabla 5) | Implementación |
|---|---|
| Plataforma de observabilidad | Grafana (alertas gestionadas y *contact point* por webhook), Prometheus (métricas), Loki con Promtail (logs) |
| Adaptador de observabilidad | `infra/observabilidad.py`: consultas de solo lectura a Prometheus y Loki |
| Agente autónomo AIOps | `agents/aiops/agente.py`: agente único con las tools de `agents/aiops/tools.py` |
| Detector/confirmador de anomalías | `Ciclo.confirmar_anomalia`: contrasta la alerta con la señal sana de su categoría |
| Motor de clasificación | `Ciclo.clasificar` y el catálogo de cinco categorías (`domain/aiops_core/catalogo.py`) |
| Motor de diagnóstico | El LLM, que registra causa, confianza y runbook (`registrar_diagnostico`) |
| Base de conocimiento | Runbooks en Markdown versionados en git (`agents/aiops/runbooks/`), entregados por `clasificar_incidente` |
| Motor de políticas | `domain/aiops_core/politicas.py`, evaluado en **cada** ejecución |
| Ejecutor | `domain/aiops_core/acciones.py` + backend Kubernetes (`infra/acciones_k8s.py`) |
| Verificador | `Ciclo.verificar`: relee la señal sana de la categoría hasta recuperar o agotar la ventana |
| Gestor de rollback | `Ciclo.revertir`, solo nivel 4 y solo si el runbook lo define |
| Escalamiento humano | `Ciclo.escalar` (paquete con evidencia y acciones), avisos a Google Chat y la UI |
| Auditoría | Registro append-only en Postgres (`aiops_eventos_auditoria`) |

**Invariantes de seguridad implementadas en código y no en el prompt:** la política se
evalúa en cada ejecución; solo se ejecutan acciones de una lista autorizada con el
servicio validado; no se cierra un incidente sin recuperación verificada; el kill switch
bloquea toda ejecución pero nunca el escalamiento; la aprobación humana queda registrada
en el dominio (quién, cuándo, veredicto) y el LLM no puede aprobarse a sí mismo.

---

## 3. RF5 y capítulo 2.3/4.2 — Conocimiento operacional (reemplaza "RAG")

**RF5 (nuevo texto).** *Obtener el procedimiento operativo aplicable a la categoría del
incidente a partir de un corpus de runbooks versionado.*

**Párrafo para 4.2, en lugar de la descripción del RAG:**

> El prototipo no emplea recuperación semántica. Cada categoría L1 del catálogo referencia
> un runbook por identificador (RB-001 a RB-005), y la herramienta de clasificación
> entrega al agente el texto del runbook correspondiente junto con la categoría. Esta
> decisión responde a tres hallazgos. Primero, la revisión de la Parte B muestra que la
> recuperación falla cuando la redacción de la alerta no coincide con el título del
> runbook y que un documento poco relevante puede otorgar una apariencia de autoridad a
> un diagnóstico débil (HackerNoon, s. f.). Con un catálogo cerrado de cinco categorías,
> la relación categoría–runbook es conocida de antemano, por lo que buscarla es una
> fuente de error innecesaria. Segundo, elimina la dependencia de un servicio de
> embeddings, de modo que el agente opera con cualquier proveedor de LLM. Tercero, la
> dependencia de un servicio externo agrega un punto de fallo al ciclo: en una corrida de
> humo en que la búsqueda no estaba disponible, el agente escaló un incidente remediable
> citando la falta de documentación. Esta observación es ilustrativa y no se atribuye al
> mecanismo como causa única: con la misma evidencia la confianza del agente varió entre
> corridas (sección 9).
>
> Los runbooks son archivos Markdown versionados en git, con metadatos de identificador,
> versión, categoría, vigencia y propietario. **[COMPLETAR: los campos de vigencia y
> propietario son hoy marcadores; deben validarse con el equipo de operaciones antes de
> la defensa.]** El contenido recuperado informa el diagnóstico pero no autoriza
> acciones: toda acción pasa por la lista autorizada y la política.
>
> La recuperación semántica sobre corpus extensos (postmortems, documentación) se
> mantiene como línea de trabajo futuro (sección 8.4).

---

## 4. Capítulo 4.2 — Modelo de datos (reemplaza el `[Pendiente]`)

> El estado del sistema se persiste en PostgreSQL. La Tabla A resume las estructuras
> relevantes. Los incidentes se almacenan como documento JSONB, indexados por
> identificador, estado y servicio, lo que evita duplicar en un esquema relacional el
> modelo de dominio y permite agregar campos sin migrar datos históricos. La auditoría es
> de solo inserción: ninguna operación actualiza ni borra eventos.

**Tabla A. Estructuras de persistencia**

| Tabla | Contenido | Observación |
|---|---|---|
| `aiops_incidentes` | Incidente completo (alerta, categoría, causa, confianza, acciones, aprobación, verificación, tokens, turnos, modelo) | JSONB; `id`, `estado`, `servicio` indexados |
| `aiops_eventos_auditoria` | Evento (instante, incidente, tipo, datos) | Solo inserción; es la fuente de la línea de tiempo y de los avisos |
| `aiops_kill_switch` | Estado del interruptor, quién y por qué | Fila única; se lee en cada evaluación de la política |
| `aiops_llm_credenciales` | API key **cifrada** por proveedor (Fernet) y sus últimos 4 caracteres | La clave nunca se devuelve por la API |
| `aiops_llm_activo` | Proveedor y modelo principal, y modelo de respaldo | Fila única |
| `aiops_notificaciones` | Bandeja de salida de avisos (estado, intentos, próximo intento) | Entrega al menos una vez |
| `checkpoints*` | Memoria de las conversaciones del chat de consulta | Generadas por LangGraph |

**Eventos de auditoría registrados:** `abierto`, `confirmacion`, `clasificacion`,
`consulta_logs`, `diagnostico`, `decision_politica`, `accion`, `verificacion`,
`aprobacion`, `cerrado`, `escalado`, `descartado`, `reconciliado`, `llm_respaldo`,
`costo_llm` y `alerta_resuelta_en_origen`.

---

## 5. Requisitos no funcionales — texto para "Integridad de herramientas" y confiabilidad

**Integridad de herramientas (reemplaza el actual).**

> El agente no consume servidores MCP de terceros: la totalidad de sus herramientas son
> funciones propias, versionadas en el repositorio y revisadas como código, lo que
> elimina la superficie de envenenamiento y de cambio posterior de definiciones descrita
> en la Tabla 3. Todo contenido externo (logs, respuestas de herramientas, texto de
> alertas, runbooks) se trata como no confiable: informa el diagnóstico pero no autoriza
> acciones, y el ejecutor solo acepta acciones de la lista autorizada.

**Confiabilidad (agregar).**

> Toda acción sobre el backend está acotada por un *timeout* de reloj de entre 60 y 120
> segundos según la acción; si vence, la acción se registra como fallida con resultado
> incierto y el agente verifica o escala sin reintentar a ciegas. Las llamadas al LLM
> tienen *timeout* y reintentos acotados. Si el proveedor principal falla a mitad de un
> incidente, un modelo de respaldo retoma el incidente desde el estado persistido. Un
> reconciliador cierra o escala los incidentes que quedaron sin cierre por la caída del
> agente, sin reintentar nunca la acción.

---

## 6. Capítulo 4.3 — Interfaces (reemplaza el `[Pendiente]`)

> **Entrada.** Grafana notifica cada alerta por *webhook* autenticado con token
> compartido (comparación en tiempo constante, rotación sin corte). El webhook procesa
> cada elemento del arreglo de alertas, deduplica por identificador y encola el trabajo;
> nunca ejecuta el agente en línea. Las alertas `resolved` se auditan sin cerrar el
> incidente: solo el agente cierra, y únicamente tras verificar.
>
> **Operación.** Una API REST expone incidentes, línea de tiempo, métricas (TRA, MTTR,
> tasa de rollback, tokens y turnos por incidente) y el kill switch, y una interfaz web
> permite aprobar o rechazar acciones (nivel 2). La interfaz se embebe en un panel de
> Grafana. La configuración del modelo de lenguaje (proveedor, modelo, respaldo y clave)
> requiere un token de administración distinto del de operación.
>
> **Consulta.** Un chat de **solo lectura** permite al operador preguntar por incidentes,
> su historial, métricas, capacidades del agente y runbooks. No dispone de herramientas
> de escritura: no ejecuta, aprueba ni escala, de modo que un texto malicioso en una
> alerta no puede convertirse en una acción por esa vía.
>
> **Escalamiento hacia L2/SRE.** Cada hito del incidente (apertura, acción, solicitud de
> aprobación, escalamiento, cierre) se notifica a un espacio de Google Chat, un hilo por
> incidente. Los avisos se generan desde la auditoría, no desde el LLM, por lo que son
> exactos y no consumen tokens. Se entregan mediante una bandeja de salida con reintentos,
> de modo que un fallo del servicio de mensajería no pierde avisos. El escalamiento
> incluye un paquete con la evidencia y las acciones realizadas.
>
> **Consulta de auditoría.** La línea de tiempo de cada incidente se obtiene por la API y
> se visualiza en la interfaz web.
>
> **[COMPLETAR si se adopta]:** integración unidireccional con la herramienta de
> ticketing de la organización (creación y actualización del ticket por incidente).

---

## 7. Capítulo 4.4 — Selección de tecnologías (reemplaza la lista de opciones)

| Función | Tecnología adoptada | Justificación |
|---|---|---|
| Alertamiento y visualización | Grafana | Alertas como código; *contact point* por webhook |
| Métricas | Prometheus | Señal independiente para confirmar y verificar |
| Logs | Loki + Promtail | Evidencia que exigen los runbooks (p. ej., RB-001) |
| Orquestación del agente | LangChain (agente de tool-calling) | Agente único con herramientas; sin multiagente |
| Modelos de lenguaje | DeepSeek, Gemini, OpenAI y Anthropic, elegibles en tiempo de ejecución | Permite comparar modelos con el mismo protocolo |
| Persistencia | PostgreSQL (JSONB) con migraciones Alembic | Estado, auditoría y configuración |
| Cola de trabajos | Redis + RQ | Desacopla el webhook de la ejecución del agente; lock por servicio |
| Backend de acciones | Kubernetes (k3d en laboratorio) con RBAC de mínimo privilegio | Acciones reversibles y de radio acotado |
| Cifrado de secretos | Fernet (cryptography) | API keys cifradas en reposo |
| Notificación | Google Chat (webhook entrante) | Canal de escalamiento y avisos |

*Alternativas consideradas y no adoptadas:* Datadog (sin acceso a la plataforma),
servidor MCP de Grafana (el agente no usa MCP; ver sección 5), trazas distribuidas
(ninguna categoría del catálogo las requiere) y recuperación semántica (sección 3).

---

## 8. Capítulo 6 — Casos y métricas

**6.2 Casos de prueba (reemplaza los candidatos).** Los cinco casos del catálogo, cada uno
con su falla inyectable, su señal de recuperación y su runbook:

| Categoría | Alerta | Señal de recuperación | Acción | ¿Remediable en el laboratorio? |
|---|---|---|---|---|
| Servicio detenido | ServiceDown | `up ≥ 1` | reinicio del servicio | Sí |
| Pod fallido | PodFailed / PodCrashLooping | `pod_ready ≥ 1` | recrear el pod | Sí |
| Disco lleno | DiskUsageHigh | uso ≤ 85 % | comprimir logs rotados (con rollback) | No: no es operación de Kubernetes |
| Cola detenida | QueueStalled | consumidores activos ≥ 1 | reiniciar consumidor | No: sin consumidor ni métricas por cola |
| Certificado por vencer | CertExpiringSoon | días restantes ≥ 14 | ninguna | No elegible: detección y escalamiento |

**6.5 Métricas.** Se mantienen TRA y reducción del MTTR como variables principales.
Complementarias medidas por el sistema: exactitud de clasificación, tasa de acciones
incorrectas (se ejecutó al menos una acción y se clasificó otra categoría o el servicio
no quedó verificado sano), tasa de escalamiento, tasa de rollback, tiempos por etapa (a
partir de la auditoría), tokens por incidente, turnos del LLM y llamadas a herramientas
por incidente. **Se retiran** el cumplimiento de SLA y la precisión y recall de
detección: las fallas son inyectadas, no existen SLA ni falsos positivos reales, y esas
métricas resultarían triviales.

**Definiciones operacionales que conviene explicitar (6.5 y Anexo D):**
- *Elegible* se determina por la **falla inyectada**, no por la clasificación del agente:
  de lo contrario, un agente que clasifica mal achicaría su propio denominador e inflaría
  la TRA.
- *MTTR* se mide desde el disparo de la alerta (la anomalía visible en Prometheus) hasta
  el cierre verificado, con el mismo inicio y fin para el agente y la línea base.
- Las corridas con fallas de infraestructura se registran aparte (`error: infra`) y se
  excluyen del análisis.

---

## 9. Limitaciones (agregar a 1.5 y a 7.3)

- Laboratorio en una sola máquina compartida: la carga externa afecta los tiempos y
  provoca fallas de infraestructura, que se registran y excluyen.
- Solo dos de las cuatro categorías elegibles son remediables en el laboratorio; las
  otras dos cuentan en el denominador de la TRA y escalan. Se reporta así, sin
  excluirlas.
- Fallas inyectadas y conocidas: sin ruido de producción, alertas espurias ni
  incidentes simultáneos.
- El nivel 2 (aprobación humana) está implementado y verificado funcionalmente, pero no
  se evalúa con el LLM.
- El LLM no es determinista: con la misma evidencia, la confianza varía entre corridas
  (en pruebas de humo, `pod_fallido` se resolvió en una de tres). Por ello el
  experimento reporta tasas con su `n` y, cuando corresponda, pass@k, no un resultado
  único.
- Con pocas repeticiones no hay significancia estadística; se reportan valores y `n`.
- La autonomía parece depender de la observabilidad disponible: en las pruebas de humo,
  cuando faltaban los logs que el runbook exige, la confianza quedó por debajo del umbral
  y el agente escaló. Es una observación preliminar con `n` pequeño, a contrastar en el
  experimento.

---

## 10. Capítulo 5.3 — Problemas encontrados y soluciones

> Durante el desarrollo se detectaron y corrigieron los siguientes problemas, todos con
> prueba automatizada. Los tres primeros son de seguridad.

| # | Problema | Solución |
|---|---|---|
| 1 | Una severidad `critical` de Grafana se interpretaba como `media`, lo que habría permitido remediar automáticamente incidentes críticos | Traducción explícita de severidades y rechazo de lo desconocido |
| 2 | Una alerta recurrente reabría un incidente ya cerrado | Un incidente terminal nunca se reabre: el nuevo disparo crea otro |
| 3 | La aprobación humana dependía solo de que el framework pausara el grafo | La aprobación se registra en el dominio y la ejecución la verifica |
| 4 | El MTTR se medía desde que el agente abría el incidente | Se mide desde el disparo de la alerta |
| 5 | Las pruebas borraban los datos del laboratorio | Base y cola Redis de pruebas aisladas |
| 6 | Las herramientas del agente operaban sobre un ciclo distinto del del worker | El worker fija el ciclo del que usan las herramientas |
| 7 | Un `rollout restart` tardó 810 s; el *timeout* de socket no acotaba la acción | *Timeout* de reloj sobre toda la acción; resultado incierto, sin reintento ciego |
| 8 | La búsqueda de runbooks dependía de un servicio externo de embeddings; al fallar, el agente escaló citando la falta de documentación | El runbook se entrega por la clasificación (sección 3) |
| 9 | En las pruebas de humo el agente escalaba citando la falta de logs que el runbook exige como evidencia | Loki y Promtail en el laboratorio; los servicios dejan constancia de sus fallas |
| 10 | Un incidente podía quedar a medias si el agente moría | Reconciliador de incidentes colgados |
| 11 | Cada incidente consumía ~65 mil tokens | Agente único de tool-calling: ~2.000 tokens fijos por llamada frente a ~5.000 **[COMPLETAR con la medición final]** |
| 12 | El escenario "servicio detenido" se autocuraba (busybox ejecuta `sleep` dentro del shell) | Bucle de `sleep` y finalización del proceso por PID |

---

## 11. Capítulo 6.3 — Resultados preliminares (solo como "pruebas de humo")

> Previo al experimento se realizaron pruebas de humo con el modelo `deepseek-chat`, nivel
> de autonomía 3, sobre el laboratorio. Estas corridas validan el funcionamiento del
> ciclo completo y orientaron decisiones de diseño; **no constituyen evidencia
> estadística** respecto de H1–H3.

| Escenario | Condición | Resultado | MTTR | Observación |
|---|---|---|---|---|
| Pod fallido | Sin runbook entregado | Escalado | – | Confianza 0,75 < 0,80 |
| Pod fallido | Runbook entregado | **Resuelto y verificado** | 81 s | Confianza 0,85 |
| Servicio detenido | Sin logs | Escalado | – | Confianza 0,60 |
| Servicio detenido | Con logs | **Resuelto y verificado** | 45 s | Confianza 0,85 |
| Certificado por vencer | – | Escalado (correcto) | – | Categoría sin acción autorizada |
| Pod fallido | Sin logs del pod, dos repeticiones | Escalado (2 de 2) | – | Confianza 0,70 y 0,60 |

> Dos observaciones, ambas preliminares. Primera: en todos los casos en que la confianza
> declarada quedó por debajo del umbral, la política impidió actuar y el agente escaló;
> ninguna acción se ejecutó con confianza insuficiente. Segunda: con la misma evidencia,
> la confianza varió entre corridas (en `pod_fallido`, 0,85, 0,70 y 0,60), por lo que una
> sola corrida no permite atribuir un resultado a un cambio de diseño. El experimento
> debe medir tasas con repeticiones.
