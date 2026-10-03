---
id: RB-004
version: 1.0
categoria: cola_detenida
servicios: consumidores de colas de trabajo
vigencia: PLACEHOLDER (validar con operaciones)
propietario: PLACEHOLDER
---

# RB-004 Cola de trabajo detenida

**Condiciones de aplicacion:** alerta `QueueStalled`, mensajes acumulandose y
`queue_consumers_active == 0`.

**Evidencia esperada:** cero consumidores activos; logs del consumidor con
desconexion o bloqueo.

**Accion autorizada:** `restart_consumer`.

**Verificacion:** `queue_consumers_active >= 1`.

**Rollback:** no aplica.

**Escalar si:** el broker esta caido, los mensajes fallan al procesarse
(mensajes envenenados) o los consumidores se vuelven a desconectar.
