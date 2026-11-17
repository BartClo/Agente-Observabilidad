---
id: RB-006
version: 1.0
categoria: contenedor_fallido
servicios: contenedores de Docker Compose de la lista permitida del host
vigencia: PLACEHOLDER (validar con operaciones)
propietario: PLACEHOLDER
---

# RB-006 Contenedor detenido o no saludable (Docker Compose)

**Condiciones de aplicacion:** alerta `ContainerStopped` o `ContainerUnhealthy`, en un
contenedor gestionado por Docker Compose, sin despliegue en curso ni mantenimiento
programado.

**Evidencia esperada:** el estado del contenedor confirma la falla, es decir, el
contenedor terminó (`exited`, por ejemplo con código 137 o 143) o su healthcheck está en
`unhealthy`, y no hay señal de causa persistente (imagen o configuración rota). El
`docker inspect` del host (estado, código de salida, OOM, reinicios, healthcheck) es
evidencia suficiente. Si hay logs, la refuerzan; que no haya logs NO la invalida.

**Accion autorizada:** `restart_service` (`docker restart` ejecutado por el host: una vez
por incidente y como máximo 3 veces por hora por servicio).

**Verificacion:** healthcheck del contenedor en `healthy` (`contenedor_sano >= 1`).

**Rollback:** no aplica.

**Escalar si:** el contenedor vuelve a caer después del reinicio, terminó por OOM
repetido, el error indica imagen o configuración inválida, o el servicio no está en la
lista permitida del host.
