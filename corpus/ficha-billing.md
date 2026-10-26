---
servicios: billing
tipo: ficha
vigente_desde: 2026-07-15
obsoleto: false
origen_dato: sintetico
---
# Ficha de servicio: billing

**Qué hace.** Registra los pagos, emite las facturas y concilia con el proveedor de
pagos. Lo llama `checkout` en cada compra.

**Despliegue.** Deployment `billing` en un namespace propio, dos réplicas, con base de
datos de pagos dedicada. Las migraciones de esquema las ejecuta el equipo de Pagos en la
ventana de los miércoles.

**Métricas clave.** `http_request_duration_seconds` p95 (objetivo 300 ms), errores 5xx por
minuto y el retraso de conciliación en minutos.

**Operación.** Un retraso de conciliación mayor de 30 minutos se trata con el proveedor de
pagos, no reiniciando el servicio. Nunca se reinicia `billing` durante el cierre contable
(último día hábil del mes, 18:00 a 22:00).

**Dueño.** Equipo de Pagos. Toda incidencia de billing se escala a su guardia.
