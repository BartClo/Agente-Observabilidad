# Hoja de ruta de la tesis: agente AIOps L1

> Estado al 2026-10-08 · último commit `cee84ee`.
>
> Este documento conecta **lo que ya está construido** con **lo que la tesis necesita
> demostrar** y ordena los pasos para cerrarla.
>
> Detalle técnico en:
> - `docs/estado-agente-aiops.md`: estado completo del agente.
> - `docs/protocolo-experimento.md`: cómo medir.
> - `docs/plan-aiops.md`: decisiones y verificaciones de cada fase.

---

## 1. La tesis en una página

**Problema.** Los incidentes operacionales recurrentes de nivel 1 (servicio caído, pod
fallido, disco lleno, cola detenida, certificado por vencer) consumen tiempo de
operadores en tareas repetitivas que siguen un runbook conocido.

**Propuesta.** Un **agente único** basado en LLM que detecta, confirma, clasifica,
diagnostica, remedia, verifica y cierra esos incidentes, o los escala con evidencia.
Opera bajo **seguridad en código**: el LLM elige qué hacer, pero una política
determinista decide si está permitido.

**Hipótesis** (definidas en `domain/aiops_core/evaluacion.py`):

| | Hipótesis | Métrica |
|---|---|---|
| **H1** | El agente resuelve solo al menos el 30 % de los incidentes elegibles | TRA ≥ 30 % |
| **H2** | Reduce el tiempo de resolución frente a la operación manual | MTTR al menos un 20 % menor que la línea base |
| **H3** | No aumenta las acciones incorrectas frente a la operación manual | Tasa de acciones incorrectas del agente ≤ la manual |

**Métricas complementarias:**
- costo en tokens por incidente;
- precisión de clasificación;
- tasa de escalamiento;
- tasa de rollback (nivel 4).

---

## 2. Dónde estamos

| Bloque | Estado | Evidencia disponible |
|---|---|---|
| Ciclo del incidente y política de seguridad | ✅ Completo | Código y tests en `domain/`, cobertura del 99 % |
| Laboratorio real (Prometheus, Grafana, RabbitMQ, k3d) | ✅ Completo | 5 fallas inyectables con `scripts/fallas/` |
| Acciones reales en Kubernetes con RBAC mínimo | ✅ Completo | Verificado en vivo: devuelve 403 fuera de lo permitido |
| Alertas de Grafana → webhook → cola → worker | ✅ Completo | Verificado en vivo |
| UI embebida en Grafana y aprobación humana (nivel 2) | ✅ Completo | Clic real del operador |
| Auditoría, kill switch y métricas (TRA, MTTR, tokens) | ✅ Completo | `/metricas`, `/metrics`, dashboard |
| Infraestructura del experimento (runner y análisis) | ✅ Completo | Corridas en modo script: `pod_fallido` en 9,7 s y `servicio_detenido` en 13,8 s |
| **LLM elegible desde la UI** (Anthropic, OpenAI, Gemini, DeepSeek) | ✅ Completo | Keys cifradas; cada incidente registra el modelo que lo atendió |
| **Agente con un LLM real** | ❌ **Nunca corrió** | Falta cargar una API key |
| Línea base manual | ❌ Pendiente | — |
| Experimento y análisis | ❌ Pendiente | — |

**En síntesis:** la ingeniería está terminada y la evaluación no empezó. Lo que falta
para la tesis es casi todo **medir y escribir**, no construir.

---

## 3. Camino crítico (en orden)

Cada paso depende del anterior. No conviene avanzar sin cerrar el previo.

### Paso 1. Poner el LLM a correr (bloqueante)

1. En `.env`:
   - `AIOPS_SECRETS_KEY`, generada con
     `python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"`;
   - `AIOPS_ADMIN_TOKEN`.
2. `alembic upgrade head` (migración `b7c2e1f4a9d0`) y reconstruir `app` y `worker`.
3. En la UI (`/ui` → "Modelo del agente"):
   - cargar la key;
   - elegir proveedor y modelo;
   - pulsar **Probar conexión**.
4. `make aiops-ingest`, para que el agente encuentre los runbooks por RAG. Usa
   embeddings de OpenAI.
5. Hacer una corrida de humo:
   ```bash
   python scripts/experimento.py --modo llm --nivel 3 --repeticiones 1 \
       --categorias pod_fallido --salida resultados/humo.csv
   ```
6. Leer la línea de tiempo en la UI:
   - ¿siguió el ciclo?
   - ¿llamó a las tools en orden?
   - ¿cuántos tokens gastó?

**Criterio de salida:** al menos una corrida resuelta y verificada por el LLM en
`pod_fallido` y otra en `servicio_detenido`.

### Paso 2. Congelar el agente

Ajustar el prompt (`agents/aiops/prompt.md`) **solo** a partir de lo observado en las
corridas de humo. Después, congelar:

- anotar el hash del commit (`git rev-parse HEAD`);
- anotar el modelo exacto;
- anotar el nivel de autonomía.

Cambiar el prompt o el modelo a mitad del experimento invalida la comparación.

### Paso 3. Línea base manual

Uno o más operadores resuelven las **mismas fallas** a mano con los runbooks, siguiendo
`docs/protocolo-experimento.md` §2. Se registra en `resultados/linea_base.csv`.

- **Mínimo:** 3 corridas por categoría.
- **Ideal:** 2 operadores o más.

Se puede hacer en paralelo con el paso 1, porque no necesita la key.

### Paso 4. Experimento principal

| Corrida | Para qué | Repeticiones |
|---|---|---|
| Nivel 3, modelo principal | Contrastar H1, H2 y H3 | ≥ 5 por categoría |
| Nivel 1, mismo modelo | Control: la TRA debe dar 0 % (el agente solo recomienda) | ≥ 2 por categoría |
| Modo script, nivel 3 | Techo de la plomería: lo que logra un diagnóstico perfecto | 3 por categoría |

### Paso 5. Análisis

```bash
python -m scripts.analizar_experimento resultados/llm-n3.csv \
    --linea-base resultados/linea_base.csv
```

Entrega tablas por categoría y el contraste de H1 a H3. Hay que complementarlo con un
**análisis cualitativo de fallas**: en cada caso no resuelto, ¿por qué?

- clasificó mal;
- tuvo baja confianza;
- la política lo denegó;
- la falla no era remediable en el laboratorio;
- hubo un error de infraestructura.

### Paso 6. Escritura

Ver la sección 5.

---

## 4. Extensiones que suman valor (opcionales, por prioridad)

| # | Extensión | Aporte a la tesis | Esfuerzo |
|---|---|---|---|
| 1 | **Comparar modelos** (Anthropic, OpenAI, Gemini y DeepSeek con el mismo protocolo) | Nueva pregunta de investigación: ¿cómo cambian TRA, MTTR y costo según el modelo? La infraestructura ya está: se cambia en la UI y el CSV trae `modelo_llm` | **Bajo** (solo correr) |
| 2 | Hacer remediable `disco_lleno` en el laboratorio | Sube la TRA alcanzable y cubre una categoría más | Medio |
| 3 | Hacer remediable `cola_detenida` (consumidor en k3d y métricas por cola) | Igual que el anterior | Medio |
| 4 | Cablear el checkpointer de LangGraph | Permite evaluar el nivel 2 con el LLM (aprobación humana real) | Medio |
| 5 | Logs en el laboratorio (Loki) | La tool `consultar_logs` aporta evidencia al diagnóstico | Bajo |
| 6 | Chat con el agente en la UI | Mejor experiencia de uso; no aporta a las hipótesis | Medio |

**Recomendación:** hacer la **1**, porque es casi gratis y convierte la tesis en un
estudio comparativo. Si sobra tiempo, la 2 o la 3. El resto se describe como trabajo
futuro.

Si se comparan modelos, agregar una pregunta **RQ4: costo frente a efectividad por
modelo**. La tabla sería:

| Modelo | TRA | MTTR | Acciones incorrectas | Tokens por incidente | Costo en USD por incidente |
|---|---|---|---|---|---|

---

## 5. Estructura sugerida del documento de tesis

| Capítulo | Contenido | Fuente en el repositorio |
|---|---|---|
| 1. Introducción | Problema, motivación, preguntas e hipótesis | Sección 1 de este documento |
| 2. Marco teórico | AIOps; operación L1 y runbooks; agentes con LLM y tool calling; seguridad en agentes autónomos; niveles de autonomía | `docs/aiops-agent.md` |
| 3. Diseño | Arquitectura; ciclo del incidente; catálogo L1; política determinista; niveles 0 a 4; decisión de agente único | `docs/estado-agente-aiops.md` §3–4 y `docs/plan-aiops.md` |
| 4. Implementación | Capas (`domain`, `infra`, `agents`, `app`); integración con Grafana y Kubernetes; persistencia y auditoría; UI; LLM multiproveedor | Código y `docs/plan-aiops.md` |
| 5. Seguridad | Invariantes en código; RBAC mínimo; kill switch; aprobación registrada en el dominio; keys cifradas; riesgos aceptados | `docs/estado-agente-aiops.md` §6 |
| 6. Metodología experimental | Laboratorio; inyección de fallas; definiciones (elegibilidad por la falla inyectada, MTTR desde el disparo, acción incorrecta); línea base; repeticiones | `docs/protocolo-experimento.md` |
| 7. Resultados | Tablas H1–H3; comparación entre modelos; costo | CSV en `resultados/` |
| 8. Discusión | Fallas del agente; qué decidió el LLM frente a la política; amenazas a la validez | Análisis cualitativo |
| 9. Conclusiones y trabajo futuro | Respuesta a las hipótesis; el camino a producción | `docs/estado-agente-aiops.md` §10.4 |

### Aportes que vale la pena destacar

- **Seguridad en código y no en el prompt.** El LLM no puede saltarse la política, el
  kill switch ni la aprobación humana.
- **Una metodología que evita inflar la TRA.** La elegibilidad sale de la falla
  inyectada y no de la clasificación del agente. El MTTR se mide desde el disparo de la
  alerta, igual que en la línea base.
- **Bugs reales que el diseño detectó.** Por ejemplo, una severidad `critical`
  interpretada como media habría permitido autoremediar incidentes críticos. La lista
  completa está en `docs/estado-agente-aiops.md` §9.

---

## 6. Amenazas a la validez (declararlas)

- **Interna:**
  - una sola máquina compartida, con tiempos afectados por carga externa (los errores
    de infraestructura se registran aparte y se excluyen);
  - fallas inyectadas y conocidas.
- **Externa:**
  - un laboratorio, no producción: sin ruido, sin alertas espurias y sin incidentes
    simultáneos;
  - el catálogo y los runbooks no están validados con un equipo de operaciones real.
- **De constructo:**
  - solo 2 de las 4 categorías elegibles son remediables en el laboratorio;
  - el nivel 2 no se evalúa con el LLM (salvo que se haga la extensión 4).
- **Estadística:** con un `n` chico no hay significancia formal. Se reportan valores y
  `n`, no p-valores.
- **Del modelo:** los LLM no son deterministas y cambian de versión. Por eso hay que
  registrar el modelo exacto y la fecha de cada corrida.

---

## 7. Checklist final

- [ ] LLM configurado y corrida de humo exitosa (paso 1)
- [ ] Prompt congelado; commit, modelo y nivel anotados (paso 2)
- [ ] Línea base: ≥ 3 corridas por categoría (paso 3)
- [ ] Experimento nivel 3: ≥ 5 repeticiones por categoría (paso 4)
- [ ] Control nivel 1 y techo en modo script (paso 4)
- [ ] (Opcional) Mismo protocolo con 2 a 4 modelos
- [ ] Tablas H1–H3 y análisis de fallas (paso 5)
- [ ] CSV crudos guardados junto con el hash del commit
- [ ] Capítulos 1 a 9 redactados (sección 5)
- [ ] Amenazas a la validez declaradas (sección 6)
