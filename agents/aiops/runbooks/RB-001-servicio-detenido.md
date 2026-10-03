---
id: RB-001
version: 1.0
categoria: servicio_detenido
servicios: cualquiera del entorno autorizado
vigencia: PLACEHOLDER (validar con operaciones)
propietario: PLACEHOLDER
---

# RB-001 Servicio detenido

**Condiciones de aplicacion:** alerta `ServiceDown`, metrica `up` en 0, sin
despliegue en curso ni mantenimiento programado.

**Evidencia esperada:** `up == 0`; logs con salida abrupta del proceso (OOM,
excepcion no capturada o señal de terminacion).

**Accion autorizada:** `restart_service` (una vez; maximo 2 intentos por politica).

**Verificacion:** `up >= 1` tras el reinicio.

**Rollback:** no aplica (reiniciar no cambia configuracion).

**Escalar si:** el servicio vuelve a caer tras el reinicio, los logs muestran
error de configuracion o dependencia caida, o hay un despliegue reciente.
