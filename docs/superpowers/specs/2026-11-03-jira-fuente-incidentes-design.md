# Jira como segunda fuente de incidentes — Diseño

> Estado: **aprobado por el autor** (2026-11-03). Rama `feature/jira`.

## 1. Objetivo

El agente atiende, además de las alertas de Grafana, los tickets de un tablero de Jira Cloud.
La conexión (sitio, correo, API token) y el tablero a escuchar se configuran desde el front.
Al terminar, el agente comenta el resultado en el ticket y lo mueve a la columna configurada.

## 2. Decisiones (con el autor)

| Tema | Elección |
|---|---|
| Rol de Jira | Otra fuente de incidentes, junto a Grafana |
| Clasificación del ticket | Etiquetas primero; si faltan, una llamada corta al LLM; el dominio valida |
| Escritura en Jira | Comenta y transiciona, solo a estados que definió el administrador |
| Tipo | Jira Cloud (`*.atlassian.net`): correo + API token, Basic auth |
| Escucha | Polling desde el scheduler del worker (enfoque 1); sin webhooks ni URL pública |

## 3. Flujo

```
scheduler del worker, cada N s
  poller ── GET tickets del tablero en la columna de entrada ──► Jira Cloud
     │  descarta los ya vistos (aiops_jira_tickets)
     │  clasifica: etiquetas → LLM de respaldo → validacion del dominio
     ▼
  Alerta(id="JIRA-<clave>", nombre=<alerta del catalogo | "JiraTicket">, servicio, resumen)
     ▼
  mismo camino que el webhook: cola → bloqueo por servicio → agente → politica
     ▼
  hito cerrado/escalado ─► bandeja de salida (canal jira) ─► comentario + transicion
```

Un ticket no es evidencia: el agente confirma con telemetría como con cualquier alerta. Si el
ticket dice "checkout caído" y Prometheus lo ve sano, no actúa: escala y lo comenta.

## 4. Clasificación

1. **Etiquetas** del ticket: `servicio:<nombre>` y `categoria:<id del catalogo>`.
2. **Respaldo LLM** (solo si falta alguna): una llamada con título y descripción saneados que
   devuelve `{servicio, categoria}` en salida estructurada. El modelo activo de la UI.
3. **Validación del dominio:** servicio en la lista de servicios conocidos
   (`AIOPS_SERVICIOS`, por defecto los del laboratorio) y categoría en `CATALOGO`. Lo que no
   valide entra con `nombre="JiraTicket"`: fuera del catálogo, se escala con comentario.

El LLM nunca elige la acción: la sigue fijando el catálogo.

## 5. Datos

- `aiops_jira_config` (fila única): `sitio`, `correo`, `token_cifrado` (Fernet, misma clave
  `AIOPS_SECRETS_KEY`), `tablero_id`, `tablero_nombre`, `estado_entrada`, `estado_resuelto`,
  `estado_escalado`, `intervalo_s` (≥ 30, por defecto 60), `activo`, `actualizado_por`,
  `actualizado_en`, `ultimo_sondeo_en`, `ultimo_sondeo_tickets`, `ultimo_error`.
- `aiops_jira_tickets`: `clave` (PK), `incidente_id`, `visto_en`, `estado`
  (`encolado|pendiente|comentado|fallido`), `destino`, `texto`, `intentos`, `ultimo_error`.
  Cada ticket se procesa **una sola vez**, y la misma tabla es la bandeja de escritura: al
  cerrar/escalar/descartar el incidente queda `pendiente` y se entrega con reintentos (la
  bandeja de Google Chat está atada a ese canal). Un comentario ya publicado no se repite si
  después falla la transición: el error queda registrado.
- El comentario sale de una plantilla sobre el incidente y la auditoría (causa, confianza,
  acciones, motivo, estado), no del LLM.

## 6. Front y API

Pestaña "Jira" en la UI embebida en Grafana, solo administrador:

1. Sitio, correo y API token (campo oculto; luego solo el sufijo). **Probar conexión**.
2. **Cargar tableros** → selector; al elegir, sus columnas.
3. Columna de entrada, estado si se resolvió, estado si se escaló.
4. Intervalo, **Activar/Pausar**, último sondeo y tickets tomados.

Endpoints (token de administración): `GET /config/jira`, `PUT /config/jira/conexion`,
`POST /config/jira/probar`, `GET /config/jira/tableros`,
`GET /config/jira/tableros/{id}/columnas`, `PUT /config/jira/tablero`,
`PUT /config/jira/activo`. El cliente manda **nombres** de columna; el servidor vuelve a leer
el tablero en Jira y resuelve los estados (no confía en ids enviados por el navegador).

## 7. Seguridad

- Token cifrado, nunca devuelto ni registrado.
- La JQL la arma el sistema con ids validados (numéricos); no hay JQL libre.
- Texto del ticket = entrada no confiable: saneado, truncado y delimitado.
- Transiciones solo a los estados configurados; no se editan otros campos ni se crean tickets.
- Tope de 5 tickets por sondeo; el kill switch sigue mandando sobre las acciones.

## 8. Tesis

Las corridas medidas fijan `AIOPS_JIRA=0` (en `AISLAMIENTO`): el núcleo medido no cambia.
Jira se presenta como capacidad adicional, evaluada aparte y de forma descriptiva.

## 9. Pruebas

Adaptador con HTTP falso; clasificación (etiquetas, respaldo, rechazo); deduplicación;
cifrado y no devolución del token; autorización de los endpoints; idempotencia del poller;
plantilla del comentario; `AIOPS_JIRA=0` apaga el poller. En vivo, con un proyecto de prueba
del autor (token cargado en la UI, nunca en el chat).

## 10. Fuera de alcance

Jira Data Center/Server, webhooks de Jira, crear tickets, editar campos, varios tableros a la
vez, JQL configurable por el usuario.
