---
servicios: worker
tipo: postmortem
vigente_desde: 2026-07-09
obsoleto: false
origen_dato: sintetico
---
# Postmortem: consumidor del worker desconectado del broker (2026-07-07)

**Resumen.** El consumidor de la cola `worker` perdió su conexión con RabbitMQ y no la
recuperó. `QueueStalled` se disparó a las 21:10 y se resolvió en 6 minutos.

**Impacto.** 140 pedidos esperaron en la cola unos 6 minutos. Sin impacto visible para
clientes.

**Línea de tiempo.**
- 21:08 el broker reinició un nodo por mantenimiento y cortó las conexiones.
- 21:10 `rabbitmq_queue_consumers{queue="worker"}` en 0; log
  `ERROR worker: conexión con el broker perdida`.
- 21:12 la guardia comprueba que el broker está sano y que no hay mensajes fallando.
- 21:13 se reinicia el consumidor.
- 21:16 el consumidor se conecta y la cola se vacía sola.

**Causa raíz.** El cliente del worker no reintentaba la reconexión tras un corte del
broker.

**Qué funcionó.** Reiniciar el consumidor, porque el broker estaba sano y los mensajes no
eran el problema.

**Acciones.**
1. Activar la reconexión automática en el cliente (planificado).
2. Antes de reiniciar, comprobar que el broker está sano y que ningún mensaje falla.

**Aprendizaje.** Si el broker está sano y el log indica pérdida de conexión, reiniciar el
consumidor lo recupera. Si tras reiniciar vuelve a caer, es otro problema.
