---
servicios: api
tipo: ficha
vigente_desde: 2026-07-15
obsoleto: false
origen_dato: sintetico
---
# Ficha de servicio: api

**Qué hace.** API de pedidos de cara a los clientes. Recibe las solicitudes del gateway,
valida el pedido y lo deja en la cola `worker` para su procesamiento asíncrono.

**Despliegue.** Deployment `api` en el namespace `aiops-lab` (Kubernetes), una réplica.
Imagen `busybox` en el laboratorio; en producción, la imagen versionada del equipo de
Pedidos. Se despliega con `kubectl -n aiops-lab apply -f` desde el repositorio de
manifiestos.

**Salud.** El `readinessProbe` ejecuta `cat /tmp/ok` cada 2 s con `failureThreshold: 1`.
Si el archivo desaparece el pod sigue vivo pero pasa a NotReady y deja de recibir tráfico.
No hay `livenessProbe`: Kubernetes no reinicia el contenedor por sí solo.

**Métricas clave.**
- `kube_pod_status_ready{condition="true",pod=~"api-.*"}`: pods listos (esperado: 1).
- `kube_pod_container_status_restarts_total`: reinicios del contenedor.
- Alerta `PodFailed` (severidad alta) cuando no hay pods listos más de 10 s.

**Logs.** Los cambios de estado del chequeo de salud se escriben una sola vez
(`ERROR api: chequeo de salud fallando`, `INFO api: chequeo de salud recuperado`). Se
consultan en Loki con `{service="api"}`.

**Dependencias.** Cola `worker` (RabbitMQ), ConfigMap `api-config` (límites y rutas),
gateway aguas arriba.

**Dueño.** Equipo de Pedidos. Escalar a su guardia si el pod no se recupera tras recrearlo
o si el fallo apareció justo después de un despliegue o un cambio de `api-config`.

**Limitaciones conocidas.** Un pod NotReady puede deberse a presión de memoria en el nodo,
a una imagen defectuosa o a un ConfigMap incorrecto; recrear el pod solo ayuda en el primer
caso. Revisar los eventos del pod (`kubectl describe pod`) antes de repetir la acción.
