---
servicios: worker
tipo: ficha
vigente_desde: 2026-07-15
obsoleto: false
origen_dato: sintetico
---
# Ficha de servicio: worker

**Qué hace.** Consumidor de la cola `worker` (RabbitMQ). Toma los pedidos que deja `api`,
los procesa (inventario, notificación al cliente) y confirma cada mensaje.

**Despliegue.** Deployment `worker` en el namespace `aiops-lab`, una réplica. Publica en
`/metrics` (NodePort 30082) el número de consumidores conectados a la cola. Se reinicia con
`kubectl -n aiops-lab rollout restart deployment/worker`.

**Métricas clave.**
- `rabbitmq_queue_consumers{queue="worker"}`: consumidores conectados (esperado: 1).
- Alerta `QueueStalled` (severidad media) cuando es menor que 1 durante más de 10 s.
- Profundidad de la cola: si crece mientras hay consumidores, el problema es de
  procesamiento (mensajes lentos o venenosos), no de conexión.

**Logs.** `{service="worker"}` en Loki. Al conectarse escribe
`INFO worker: consumidor conectado a la cola 'worker'`; al perder la conexión escribe un
`ERROR` con el motivo.

**Dependencias.** RabbitMQ (broker), servicio de inventario, correo saliente.

**Dueño.** Equipo de Pedidos. Escalar si el consumidor se reconecta y vuelve a caer, si el
broker está caído o si los mensajes fallan al procesarse (ver postmortem de mensajes
venenosos).

**Limitaciones conocidas.** Un consumidor desconectado y un consumidor atascado en un
mensaje venenoso producen la misma alerta. En el segundo caso reiniciar el consumidor lo
reconecta, pero vuelve a tomar el mismo mensaje y a caer.
