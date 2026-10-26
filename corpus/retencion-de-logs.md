---
servicios:
tipo: guia
vigente_desde: 2026-08-01
obsoleto: false
origen_dato: sintetico
---
# Retención de logs

**Política.** Loki conserva 14 días de logs de todos los servicios. Los logs de auditoría
de incidentes se guardan 12 meses en Postgres.

**Comprimir logs antiguos.** En los servidores con disco propio, un proceso comprime los
archivos de más de 7 días. Hacerlo a mano solo se justifica si el disco supera el 90 % y
se avisa a quien opera el servidor; no se borran logs, se comprimen.

**Datos sensibles.** Los logs no deben contener contraseñas, tokens ni datos personales.
Si aparecen, se reporta a Seguridad y se enmascaran antes de compartirlos.

**Consultas útiles.** `{service="checkout"} |= "ERROR"` para los errores de un servicio;
acotar siempre el rango de tiempo al incidente para no mezclar eventos de otras fechas.
