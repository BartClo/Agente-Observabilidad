# Conectar el agente a otro ambiente

Sirve para otro stack Grafana, Prometheus (o compatible: Mimir, Thanos), Loki y Kubernetes.
Otras herramientas necesitan un adaptador que implemente `ObservabilidadPort`. Sin `AIOPS_PERFIL`,
el agente se comporta como siempre.

## Pasos

1. Generar un borrador. Solo lee y escribe un archivo:
   ```bash
   python -m scripts.conectar_ambiente --prometheus http://prom:9090 --entorno qa --salida perfiles/qa.yaml
   ```
   Con Grafana, agregar `--reglas-url http://grafana:3000/api/prometheus/grafana/api/v1/rules`.
2. Revisar el archivo: los avisos `# REVISAR`, las etiquetas, las consultas y `kubernetes`.
3. Aprobarlo con `aprobado: true` y `aprobado_por: <responsable>`. Sin eso, el agente no arranca.
4. Definir en el entorno, nunca en el perfil:
   - `AIOPS_PERFIL`.
   - `AIOPS_PROMETHEUS_URL` y `AIOPS_LOKI_URL`.
   - Credenciales si hacen falta: `AIOPS_PROMETHEUS_AUTH` y `AIOPS_LOKI_AUTH` (valor completo del
     encabezado, por ejemplo `Bearer ...`) y `AIOPS_OBS_ORG_ID` (`X-Scope-OrgID`).
   - `AIOPS_ALLOWED_ENVS`, que debe incluir el `entorno` del perfil.
   - `AIOPS_AUTONOMY_LEVEL`, el tope global.
5. Apuntar el contact point de Grafana a `POST /webhooks/alertas` con el token de la API.
6. Observar en nivel 1 (simulacro) y subir `nivel` por categoría cuando los resultados lo respalden.

## Ejemplo

```yaml
version: 1
aprobado: true
aprobado_por: ana@equipo
entorno: pre-prod
observabilidad: {etiqueta_servicio: aplicacion, etiqueta_logs: container}
consultas:
  sonda_http: 'min(blackbox_ok{aplicacion="$servicio"})'   # debe usar $servicio
categorias:
  - id: web_caida
    alertas: [TiendaSinRespuesta]
    runbook: RB-001               # debe existir en agents/aiops/runbooks
    senal: {metrica: sonda_http, operador: ">=", umbral: 1}
    accion: restart_service       # de la lista autorizada del código
    nivel: 3                      # si falta, 1 (observación)
kubernetes:
  namespaces: [tienda]
  etiqueta_app: app
  servicios:
    tienda-web: {namespace: tienda, deployment: tienda-web-v7, selector: tienda-web}
```

La sección opcional `webhook` mapea campos con rutas (`nombre`, `servicio`, `severidad`, `resumen`,
`inicio`, `huella`, `estado`, `valor_firing`, `lista`, `severidades`). Por defecto usa el formato
de Grafana y Alertmanager.

## Límites de seguridad

- Un perfil solo acota: no supera `AIOPS_AUTONOMY_LEVEL` ni `AIOPS_ALLOWED_ENVS`, y las acciones
  salen de la lista del código.
- El entorno lo fija el perfil, nunca el payload del webhook.
- Una severidad desconocida se trata como crítica, así que no se actúa solo.
- Una alerta fuera del catálogo la atiende un agente sin tools que remedien: investiga y escala.
- Un namespace fuera de `kubernetes.namespaces` se niega antes de llamar a la API. El RBAC del
  ServiceAccount debe ser igual de estrecho: el perfil no lo reemplaza.
- Nivel 2: la aprobación desde la UI retoma el incidente con un job nuevo.

## Sin verificar

Todo esto se probó con dobles (`tests/test_ambiente_nuevo_e2e.py`), no contra un ambiente real ni
con el LLM. Falta en especial la reanudación de nivel 2 y el modo investigación con un modelo real.
