# Runbook de operación del agente aiops

Cómo operar el **propio agente**: levantarlo, frenarlo, aprobar, rotar credenciales y
qué hacer cuando algo falla. Para los runbooks de los incidentes que el agente atiende,
ver `agents/aiops/runbooks/`. Para el diseño, `docs/aiops-agent.md` y `docs/plan-aiops.md`.

## Piezas y dónde mirar

| Pieza | Qué hace | Dónde mirar |
|---|---|---|
| Grafana (`:3001`) | Evalúa las reglas L1 y manda el webhook | Dashboard "AIOps L1" (`/d/aiops-l1`) |
| API (`api`, `:8010`) | Recibe el webhook, encola, sirve la UI y las métricas | `docker compose logs api` |
| Worker (`worker`) | Atiende cada alerta: abre el incidente e invoca al agente | `docker compose logs worker` |
| Redis | Cola de trabajos y lock por servicio | Métrica `aiops_jobs_fallidos` |
| Postgres | Incidentes, auditoría, kill switch | UI (`/ui`) o `GET /incidentes/{id}` |
| k3d (`aiops-lab`) | Cluster donde el agente actúa | `kubectl -n aiops-lab get pods` |

## Levantar y bajar

```bash
make migrate                                                    # una vez por base nueva
docker compose --profile observability --profile redis up -d    # laboratorio completo
k3d cluster start aiops-lab                                     # si se usa pod_fallido

docker compose --profile observability --profile redis stop     # bajar sin borrar datos
k3d cluster stop aiops-lab
```

El agente **no actúa** solo con levantarlo: hace falta `AIOPS_BACKEND=prometheus`,
`AIOPS_ACTIONS=k8s` (con su token, ver abajo) y un nivel de autonomía ≥ 2. El default
del repo (`AIOPS_AUTONOMY_LEVEL=1`) solo diagnostica y escala.

## Frenar todo: kill switch

Bloquea **toda** ejecución de acciones; el agente sigue detectando y escalando.

- UI: tarjeta "Kill switch" → **Activar** (pide motivo, queda auditado).
- API: `curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"usuario":"yo","activo":true,"motivo":"..."}' http://localhost:8010/kill-switch`

Rige para todo proceso con `AIOPS_PERSISTENCIA=postgres` (API y worker). Se lee en cada
evaluación de la política: no hace falta reiniciar nada.

## Cambiar el nivel de autonomía

`AIOPS_AUTONOMY_LEVEL` (0–1 recomienda, 2 con aprobación, 3 autónomo bajo riesgo, 4 +
rollback). Se lee al arrancar el proceso: cambiar en `.env` y
`docker compose restart worker api`. Para empezar en un entorno nuevo, subir de a un
nivel y mirar la línea de tiempo de los incidentes antes de seguir.

## Aprobar o rechazar (nivel 2)

UI → fila "esperando aprobación" → **Aprobar** o **Rechazar** (pide motivo; el
incidente se escala). Queda en la auditoría con el usuario indicado en la UI. Un
incidente aprobado por un humano **no cuenta** para la TRA.

## Rotar el token de la API (sin corte)

`AIOPS_API_TOKEN` acepta varios valores separados por coma.

1. `AIOPS_API_TOKEN=viejo,nuevo` y `docker compose restart api`.
2. Actualizar los clientes: el contact point de Grafana
   (`docker/grafana/provisioning/alerting/contact-points.yaml`, reiniciar Grafana) y
   los operadores (la UI pide el token).
3. `AIOPS_API_TOKEN=nuevo` y `docker compose restart api`.

Generar tokens con `openssl rand -hex 32`. Nunca commitear `.env`.

## Rotar el token del ServiceAccount de Kubernetes

```bash
kubectl -n aiops-lab delete secret aiops-agent-token
kubectl apply -f k8s-lab/rbac-aiops.yaml          # recrea el Secret con un token nuevo
kubectl -n aiops-lab get secret aiops-agent-token -o jsonpath='{.data.token}' | base64 -d > k8s-lab/.secrets/token
docker compose restart worker
```

El token viejo deja de valer al borrar el Secret. Los permisos no cambian: los fija el
Role (`k8s-lab/rbac-aiops.yaml`), no el token.

## Síntomas frecuentes

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| Incidente escalado con "sin datos de …: evidencia insuficiente" | Prometheus sin scrapes recientes (recién levantado, máquina suspendida) o target caído | Revisar targets en Prometheus (`:9090/targets`). Subir `AIOPS_CONFIRM_WINDOW_S` (p. ej. 30) para tolerar huecos cortos. |
| Escalado con "API de Kubernetes respondió 403" | La acción pide un permiso que el Role no da (correcto si la acción no es del catálogo) | No ampliar el Role sin revisar; ver qué acción se intentó en la línea de tiempo. |
| Escalado con "no soportada por el backend Kubernetes" | `compress_old_logs`/`restore_compressed_logs`: no son operaciones de Kubernetes | Esperado: `disco_lleno` se atiende a mano o con otro backend. |
| `aiops_jobs_fallidos` > 0 | Un job agotó sus reintentos (LLM caído, timeout, servicio ocupado mucho tiempo) | Ver la causa: `docker compose run --rm app uv run rq info --url $REDIS_URL` y el `exc_info` del job en el FailedJobRegistry de la cola `aiops`. |
| Alertas que llegan pero nadie las atiende | Worker caído, o escuchando otra cola | `docker compose ps worker`; debe escuchar `default` y `aiops`. |
| Incidentes "esperando aprobación" que no avanzan después de aprobar | El proceso que atiende ese incidente no usa Postgres | API y worker con `AIOPS_PERSISTENCIA=postgres`. |
| Todo escala aunque la autonomía sea 3 | Severidad `critical` en la regla, confianza < umbral, entorno no permitido o kill switch activo | La razón exacta está en el evento `decision_politica` de la línea de tiempo. |
| `make test` vacía la UI | (Corregido en la Fase 6) los tests usan `<base>_test` y la base `/15` de Redis | Si vuelve a pasar, revisar que `conftest.py` de la raíz se esté cargando. |

## Qué NO hacer

- No montar `docker.sock` en ningún servicio para "darle más alcance" al agente.
- No ampliar el Role de Kubernetes para que una acción "funcione": si la política o el
  RBAC dicen que no, el diseño es escalar.
- No habilitar `GF_PANELS_DISABLE_SANITIZE_HTML` en una instancia de Grafana compartida:
  quien edite un dashboard podría inyectar HTML/JS. Usar un plugin de panel.
- No usar los valores del laboratorio (`lab-secret-token`, `admin/admin`, los secretos
  de `docker/garage/garage.toml`) fuera de la máquina local.
