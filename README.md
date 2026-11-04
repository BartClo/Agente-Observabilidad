# Agente AIOps para incidentes L1 · integración con Jira

> **Rama `feature/jira` (trabajo).** Es el agente de la tesis (rama `master`) más la
> integración con **Jira Cloud** que se pidió en el trabajo: los tickets del tablero
> entran como incidentes y el agente responde en el mismo ticket. La tesis se evalúa
> sobre `master`; durante el experimento, Jira se apaga con `AIOPS_JIRA=0`.

## Integración con Jira

```
Tablero Jira (columna de entrada) ──poller (worker RQ)──► Alerta JIRA-<clave> ──► misma cola que Grafana
                                                                                   │
  ticket: comentario con el resultado + transición a "resuelto" o "escalado" ◄──────┘
```

- **Entrada:** un job del worker consulta el tablero cada N segundos (60 por defecto).
  Cada ticket nuevo se encola una sola vez como `INC-JIRA-<clave>` y sigue el mismo
  ciclo que una alerta de Grafana.
- **Clasificación:** primero las etiquetas `servicio:<nombre>` y `categoria:<id>`; si
  faltan, decide el LLM y el resultado se valida contra el catálogo. Si no valida, el
  ticket se escala.
- **Salida:** al cerrar, escalar o descartar, el agente comenta el resultado y mueve el
  ticket a la columna configurada. Si la transición falla, el comentario no se repite.
- **Seguridad:**
  - el token se guarda cifrado (Fernet, `AIOPS_SECRETS_KEY`) y solo se muestran sus
    últimos 4 caracteres;
  - el sitio tiene que ser `https://<x>.atlassian.net`;
  - el JQL se arma solo con ids numéricos;
  - el entorno sale de `AIOPS_JIRA_ENTORNO`, nunca de las etiquetas del ticket.

### Conectarlo

1. Crear un API token en <https://id.atlassian.com/manage-profile/security/api-tokens>.
2. En la UI, pestaña **Configuración** → bloque **Jira**, con el token admin:
   1. **Conexión:** sitio, correo y token; después **Probar**.
   2. **Tablero y columnas:** de entrada, de resuelto y de escalado, y el intervalo.
   3. **Escucha:** **Activar escucha**.

El token se carga solo en la UI, nunca en el código ni en el chat. Detalle en la decisión
D22 de [`docs/decisiones-robustez.md`](docs/decisiones-robustez.md).

## Otros ambientes

Con un perfil YAML (`AIOPS_PERFIL`), el agente se conecta a otro Grafana, Prometheus, Loki y
Kubernetes sin cambiar código: alertas, consultas, namespaces y autonomía por categoría. Todo
ambiente nuevo parte en observación, y lo desconocido se investiga sin actuar y se escala.
Hasta ahora solo está probado con dobles, no contra un ambiente real. Guía en
[`docs/ambientes.md`](docs/ambientes.md).

---

## Hipótesis

| | Hipótesis | Métrica |
|---|---|---|
| **H1** | El agente resuelve solo al menos el 30 % de los incidentes elegibles | TRA ≥ 30 % |
| **H2** | Reduce el tiempo de resolución frente a la operación manual | MTTR ≥ 20 % menor que la línea base |
| **H3** | No aumenta las acciones incorrectas frente a la operación manual | Acciones incorrectas del agente ≤ las manuales |

Métricas complementarias: costo en tokens por incidente, precisión de clasificación,
tasa de escalamiento y tasa de rollback. Las definiciones están en
`domain/aiops_core/evaluacion.py`, con tests.

## Categorías de incidente

| Categoría | Acción autorizada | ¿Remediable en el laboratorio? |
|---|---|---|
| `servicio_detenido` | `restart_service` | Sí |
| `pod_fallido` | `recreate_pod` | Sí |
| `cola_detenida` | `restart_consumer` | Sí (consumidor simulado) |
| `disco_lleno` | `compress_old_logs` | No: es elegible pero escala, y eso baja la TRA |
| `certificado_por_vencer` | ninguna | No es elegible: escala por diseño |

## Cómo funciona

```
Alertmanager / Grafana ──webhook──► API (FastAPI) ──► cola RQ (Redis) ──► worker
                                                                          │
     ┌────────────────────────────────────────────────────────────────────┘
     ▼
  ciclo del incidente (domain/aiops_core/ciclo.py)
     confirmar con telemetría (Prometheus, Loki) → clasificar → diagnosticar (LLM + runbooks)
     → política en código (catálogo, límites, kill switch) → acción en Kubernetes
     → verificar → cerrar  |  escalar con evidencia (o pedir aprobación humana)
     │
     ▼
  auditoría en Postgres  ──►  UI (/ui, embebida en Grafana) · notificaciones
```

- **El LLM no calcula, elige tools.** La lógica vive en `domain/aiops_core/`, Python puro
  y testeable.
- **Kill switch** y **aprobación humana** para las acciones de mayor riesgo.
- **Fuentes de incidentes:** webhook de Alertmanager o Grafana y, en esta rama, tickets de Jira.
- **Fallback de LLM:** si el modelo principal falla a mitad de un incidente, el de
  respaldo lo retoma desde donde quedó.
- **Saneamiento** de secretos y de texto hostil antes de enviar contexto al LLM o de
  mostrarlo.
- Cada paso queda auditado y es reproducible; los experimentos corren aislados (`AISLAMIENTO`
  en `scripts/experimento.py`).

## Estructura

```
agents/aiops/       Agente: prompt, tools, runbooks, skills, worker, chat de consulta
domain/aiops_core/  Ciclo, políticas, catálogo, evaluación, métricas, saneamiento (puro)
app/                API HTTP (api.py) y UI (ui/index.html)
infra/              Postgres, Redis/RQ, Kubernetes, LLM, cifrado de configuración
k8s-lab/            Laboratorio k3d: workloads, RBAC, inyección de fallas
scripts/            experimento.py, linea_base.py, analizar_experimento.py, congelar.py
migrations/         Alembic
docs/               Decisiones, protocolo, hoja de ruta, textos de la tesis
tests/              Suite unitaria y de integración (Postgres y Redis reales)
```

## Inicio rápido

Todo corre dentro de contenedores; `uv` solo existe ahí.

```bash
cp .env.example .env                    # claves del LLM y AIOPS_* (nunca se commitean)
k3d cluster start aiops-lab
docker compose --profile '*' up -d
kubectl apply -f k8s-lab/
```

- UI: `http://localhost:8010/ui` (también embebida en Grafana, `http://localhost:3001`)
- Tests: `MSYS_NO_PATHCONV=1 docker compose run --rm app uv run pytest -q`
- Lint y tipos: `make check` (ruff + mypy strict + cobertura)
- Bajar todo: `docker compose --profile '*' down && k3d cluster stop aiops-lab`

## Experimento

1. **Congelar** la versión evaluada: `scripts/congelar.py`.
2. **Línea base manual:** `scripts/linea_base.py`; un operador resuelve las mismas fallas
   siguiendo los runbooks.
3. **Corridas del agente:** `scripts/experimento.py` inyecta cada falla en k3d y mide.
4. **Análisis:** `scripts/analizar_experimento.py` calcula TRA, MTTR, acciones incorrectas
   y costo, siempre reportados con su `n`.

Protocolo completo en [`docs/protocolo-experimento.md`](docs/protocolo-experimento.md).

## Documentación

| Documento | Contenido |
|---|---|
| [`docs/hoja-de-ruta-tesis.md`](docs/hoja-de-ruta-tesis.md) | La tesis en una página y los pasos para cerrarla |
| [`docs/protocolo-experimento.md`](docs/protocolo-experimento.md) | Qué se mide, cómo y sus limitaciones |
| [`docs/estado-agente-aiops.md`](docs/estado-agente-aiops.md) | Estado completo del agente |
| [`docs/arquitectura-y-flujos.md`](docs/arquitectura-y-flujos.md) | Componentes y flujo de un incidente |
| [`docs/decisiones-robustez.md`](docs/decisiones-robustez.md) | Decisiones de diseño (D1…), con su porqué |
| [`docs/runbook-operacion.md`](docs/runbook-operacion.md) | Operación: kill switch, aprobaciones, credenciales, fallas |
| [`docs/getting-started.md`](docs/getting-started.md) | Instalación y variables de entorno |
| [`docs/textos-para-la-tesis.md`](docs/textos-para-la-tesis.md) | Textos listos para el documento de tesis |
| [`k8s-lab/README.md`](k8s-lab/README.md) | Laboratorio k3d |

## Stack

Python 3.12 · deepagents · FastAPI · RQ + Redis · Postgres · Prometheus · Loki · Grafana ·
k3d · Docker Compose · ruff · mypy (strict) · pytest.

## Estado

El agente está implementado y probado, y la suite pasa completa. Lo que falta para la
tesis es congelar la versión, correr el experimento final, analizar los resultados y
redactarla. Ver [`docs/hoja-de-ruta-tesis.md`](docs/hoja-de-ruta-tesis.md).
