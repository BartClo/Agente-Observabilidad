---
servicios: worker
tipo: postmortem
vigente_desde: 2026-05-19
obsoleto: false
origen_dato: sintetico
---
# Postmortem: worker atascado por un mensaje venenoso (2026-05-17)

**Resumen.** La cola `worker` dejó de consumirse durante 2 horas 10 minutos. `QueueStalled`
se disparó a las 03:20; la guardia reinició el consumidor tres veces sin resolverlo.

**Impacto.** 1.900 pedidos acumulados en la cola. Los clientes recibieron la confirmación
con retraso; ningún pedido se perdió.

**Línea de tiempo.**
- 03:20 `rabbitmq_queue_consumers{queue="worker"}` en 0.
- 03:26 se reinicia el consumidor: se conecta (`INFO worker: consumidor conectado`) y a
  los 20 s vuelve a caer con `ERROR worker: fallo procesando mensaje 88123`.
- 03:41 y 04:02 dos reinicios más, mismo patrón.
- 04:30 se mira la cola: el mismo mensaje se entrega una y otra vez.
- 05:25 se mueve el mensaje a la cola de errores y el consumo se normaliza.

**Causa raíz.** Un pedido con una dirección malformada provocaba una excepción no
controlada en el procesamiento; sin límite de reintentos, el mensaje volvía a la cola
infinitamente.

**Qué no funcionó.** Reiniciar el consumidor: se reconectaba bien y volvía a tomar el
mismo mensaje.

**Acciones.**
1. Limitar los reintentos y enviar a una cola de errores (hecho, ver `cambios-recientes.md`).
2. Validar la dirección antes de encolar.

**Aprendizaje.** Un consumidor que se desconecta de forma repetida tras reiniciarlo apunta
a un problema de procesamiento, no de conexión. Hay que escalar.
