# Aportes de las fuentes prácticas al agente

> Lectura de fuentes **no académicas** (blogs de ingeniería, documentación de proveedores,
> repositorios abiertos) hecha el 2026-10-25, con lo que cada una aporta al proyecto.
> No es evidencia independiente: casi todas son blogs o documentación de proveedores.
> Donde solo vi un resumen (no el texto original) se dice.
>
> Convención de fiabilidad: **A** = leída completa y es del autor del sistema o una guía
> institucional; **B** = blog o documentación de un proveedor; **C** = solo un resumen de
> buscador o una fuente patrocinada.

## 1. Fuentes y qué dicen

| Fuente | Nivel | Hallazgo útil |
|---|---|---|
| [Google SRE — AI en operaciones confiables](https://sre.google/resources/practices-and-processes/ai-engineering-reliable-operations/) | A | Autorización progresiva (L0–L4) y "los agentes no reciben acceso completo desde el día uno". Límites de tasa y **cortacircuitos específicos del agente**. Identidad propia del agente, no las credenciales de sus desarrolladores. **`dry_run` obligatorio** en toda API que use un agente. Baja de L3 a L2 ante riesgo elevado. La autonomía sube solo tras "tasas de éxito sostenidas y estadísticamente significativas" sobre datos de oro |
| [Google SRE — podcast](https://sre.google/prodcast/transcripts/sre-prodcast-04-09/) | A | Las escrituras en producción requieren aprobación humana; zonas horarias mezcladas confundieron a un agente; evaluar contra postmortems humanos; "hill climbing" sobre el mismo conjunto |
| [Datadog — plataforma de evaluación](https://www.datadoghq.com/blog/engineering/bits-ai-eval-platform/) | B | Telemetría con ruido bajó el pass rate ~11 % y lo hizo más predictivo; pass@k; evaluar la trayectoria; el conjunto completo se corre semanalmente porque una mejora en pocos casos empeoró en el total |
| [Zof — kill switches y cortacircuitos](https://zof.ai/blog/kill-switches-and-circuit-breakers-designing-graceful-stand-down-for-reliability-agents) | C | Nueve patrones: de tasa, **de remediación repetida** (misma acción, mismo destino, el síntoma no cede), de novedad, de radio de impacto, falla segura ante entradas viejas, *stand-down* limpio y traspaso con contexto. Sin umbrales numéricos |
| [SoftwareSeni — arquitectura de seguridad](https://www.softwareseni.com/ai-sre-safety-architecture-guardrails-escalation-paths-and-human-control) | C | Tres capas de control; disparadores concretos de escalamiento (identificador fuera del registro, privilegio no concedido, respuestas del LLM que discrepan); contenido del traspaso a un humano |
| [DEV — frontera de autonomía](https://dev.to/pradeep_kandepaneni/the-autonomy-boundary-pricing-your-aiops-agent-in-both-error-budget-and-dollars-e2a) | C | **La confianza es completitud de la evidencia, no la certeza que declara el modelo.** Es una compuerta dura: bajo el umbral nunca se actúa. Los límites se aplican en infraestructura, no en la lógica del agente |
| [HackerNoon — runbooks + RAG](https://hackernoon.com/runbooks-rag-how-i-gave-my-ai-sre-agent-the-context-it-was-missing) | B | Meter el conocimiento en el prompt falló. `last_validated` en cada runbook, citar qué documentos sustentan cada hipótesis, el texto recuperado no autoriza acciones. Los postmortems son lo más valioso |
| [CSO Online — etapas de autonomía](https://www.csoonline.com/article/4183666/what-sre-teams-need-before-they-trust-ai-agents.html) | B | Cinco etapas muy parecidas a nuestros niveles. **No define umbrales ni criterios para bajar de etapa** |
| [Azure SRE Agent](https://sre.azure.com/docs/get-started/automate-incidents) | B | Modos Review y Autonomous; filtros por severidad; **período de espera para no reinvestigar la misma alerta**. No documenta concurrencia ni escalamiento |
| [IBM — ITBench-AA](https://huggingface.co/blog/ibm-research/itbench-aa) | B | Más turnos no mejora (31 turnos: 46 %; 83 turnos: 30 %); sobreinvestigar suma falsos positivos; 3 repeticiones por tarea; costo por tarea de 0,14 a 5,38 USD |
| [HolmesGPT](https://github.com/HolmesGPT/holmesgpt) | B | Salida de tools acotada (filtrado en servidor, presupuesto de salida). Dice ser de solo lectura pero incluye un toolset de remediación: hay que verificar si está protegido |
| [OpenSRE](https://github.com/tracer-cloud/opensre) | B | Enmascarado reversible de identificadores antes de llamar al LLM; una prueba de alta señal por clase de falla; límites de importación entre capas. **Su `SECURITY.md` es solo una política de reporte de vulnerabilidades** |
| [IncidentFox](https://github.com/incidentfox/incidentfox) | B | Proxy que inyecta las credenciales (el agente nunca las ve) y un *sandbox* por investigación. Archivado, y esa parte está bajo licencia BSL: no se puede reutilizar |
| [Cloud Security Alliance](https://labs.cloudsecurityalliance.org/research/csa-research-note-mcp-tool-poisoning-ai-agent-exfiltration-2/) | B | Controles contra envenenamiento de tools MCP. **No cubre inyección por logs** |
| Búsqueda sobre inyección por telemetría (AIOpsDoom, USENIX Security 2026; STAR Labs; DEF CON) | C | Un log puede empujar a un agente hacia una remediación dañina sin dar una orden explícita, y evade los filtros de prompt. Las salidas estructuradas y limitar lo que el agente puede hacer reducen el daño. Solo vi resúmenes |
| Búsqueda sobre confianza verbalizada (varios preprints) | C | La confianza que declara un LLM no es fiable como compuerta; hay que usar verificaciones externas |
| [SREGym](https://arxiv.org/abs/2605.07161) | C | 90 problemas con inyectores de fallas y de ruido sobre Prometheus, Loki y kubectl. Un resumen secundario dice que los agentes pierden 7–30 % con ruido; no lo confirmé en el paper |

**No pude leer** los tres artículos de Komodor (error 403).

## 2. Lo que nuestro diseño ya cubre

- **La acción no la elige el LLM.** La categoría sale de la alerta y la acción de esa
  categoría en el catálogo; el LLM solo diagnostica y llama a `ejecutar_remediacion` sin
  parámetros. Es justo la defensa que las fuentes de inyección recomiendan (limitar lo que
  el agente puede hacer), pero **hay que demostrarlo con una prueba**, no afirmarlo.
- Lista autorizada, servicio validado, kill switch leído en cada evaluación, RBAC de un
  solo namespace, identidad propia (ServiceAccount), el LLM nunca ve credenciales.
- "Sin datos = sin evidencia → escalar" (falla segura ante entradas ausentes).
- Verificación independiente antes de cerrar; auditoría append-only; tokens y turnos por
  incidente; aprobación humana registrada en el dominio.

## 3. Brechas y propuestas

| # | Brecha | Propuesta | Fuentes |
|---|---|---|---|
| 1 | La política depende de la **confianza que declara el LLM**, que varió de 0,60 a 0,85 con la misma evidencia | **Compuerta de evidencia determinista** en el dominio: cada categoría exige las señales de su runbook ("Evidencia esperada") y las comprueba el código. La confianza queda como criterio secundario. Evaluarlo como **ablación** (solo confianza / solo evidencia / ambas) con las mismas corridas | DEV, preprints sobre confianza, nuestras corridas |
| 2 | El tope de reintentos es **por incidente**: una alerta que reaparece tras cada reinicio crea otro incidente y otro reinicio | **Cortacircuito entre incidentes**: máximo de acciones autónomas por servicio en una ventana; misma acción sin que ceda el síntoma → escalar como "recurrente"; al dispararse, degradar a nivel 2 en vez de parar todo | Zof, Google, Azure, CSO (hueco de "bajar de etapa") |
| 3 | Los logs llegan crudos al LLM (sin enmascarado ni tope por línea). **Tu Tabla 3 promete el enmascarado** | Enmascarar secretos, correos e IP; truncar líneas largas. Añadir un **escenario de inyección** en un log del lab y verificar que la política lo contiene | OpenSRE, Komodor (vía Tabla 3), AIOpsDoom, CSA |
| 4 | No hay `dry_run` antes de actuar | Kubernetes admite `dryRun=All`: validar permisos y existencia del destino antes del cambio real | Google |
| 5 | Una corrida no basta (lo vivimos con el agente único) | Suite de regresión (5 escenarios × k) tras cada cambio; corridas de **ajuste** separadas de las del experimento final; **intervalos de confianza** (Wilson) en el análisis | Datadog, Google, IBM |
| 6 | El lab no tiene ruido | Un servicio sano con errores inocuos y una alerta ajena; opcionalmente Chaos Mesh o LitmusChaos como inyectores estándar | Datadog, SREGym |
| 7 | El traspaso a L2 mezcla hechos e inferencias | Separar "hechos verificados" (salida de tools) de "inferencias del LLM" y agregar "qué haría a continuación" | CSO, Zof, SoftwareSeni |
| 8 | No se guarda el razonamiento, solo eventos | Persistir la trayectoria (Langfuse ya está en el compose); encadenar hashes en la auditoría para que sea verificable | Google, SoftwareSeni |
| 9 | Los runbooks tienen `vigencia`/`propietario` como marcadores | Fecha real en `last_validated`; postmortem automático por incidente desde la auditoría | HackerNoon |
| 10 | La tesis (3.4) pide factibilidad económica | Guardar el precio por modelo y calcular el costo en USD por incidente | DEV (cifras modeladas), IBM |

## 4. Aportes posibles de la tesis

- Un **criterio explícito para subir y bajar de nivel de autonomía** (las fuentes lo dejan
  sin umbral).
- Que **la acción la determine el catálogo y no el LLM** como defensa de diseño frente a la
  inyección por telemetría, con su prueba de seguridad.
- La **ablación confianza declarada vs. compuerta de evidencia**, con datos propios.
- La observación de que la **autonomía depende de la observabilidad disponible**
  (preliminar: ver `docs/textos-para-la-tesis.md`, sección 9).

## 5. Por verificar antes de citar

- Tabla 1 de la tesis dice que OpenSRE tiene "suites sintéticas de RCA que miden la
  resistencia a señales engañosas". En su README **no lo encontré**; revisar `tests/`.
- Las cifras de SREGym por agente y el resultado de AIOpsDoom los vi solo en resúmenes.
- Los umbrales de Zof y SoftwareSeni (30 s, 2 semanas de observación) son recomendaciones,
  no mediciones.
