---
servicios:
tipo: guia
vigente_desde: 2026-09-20
obsoleto: false
origen_dato: sintetico
---
# Registro de cambios recientes

Cambios de producción de las últimas semanas, del más nuevo al más antiguo. Ante un
incidente, revisar si hubo un cambio en las horas previas en el servicio afectado.

| Fecha | Servicio | Cambio | Responsable |
|---|---|---|---|
| 2026-09-18 | checkout | Límite de memoria subido de 256 Mi a 384 Mi | Pagos |
| 2026-09-12 | gateway | Renovación del certificado TLS (vence 2027-09-12) | Plataforma |
| 2026-09-05 | worker | Reintentos de mensajes fallidos: de 5 a 3, luego cola de errores | Pedidos |
| 2026-08-28 | api | Nueva versión 2.4.1: validación de direcciones | Pedidos |
| 2026-08-20 | billing | Migración de esquema de pagos (sin cambio de API) | Pagos |
| 2026-08-14 | api | `api-config`: tiempo máximo de solicitud de 10 s a 5 s | Pedidos |
| 2026-08-01 | plataforma | Retención de logs en Loki: 14 días | Plataforma |

**Cómo usarlo.** Un fallo que aparece pocas horas después de un cambio se trata como
posible regresión: reiniciar o recrear rara vez lo arregla y conviene hablar con el
responsable del cambio. Un fallo sin cambios recientes y con síntomas de recursos
(memoria, conexiones) suele ser operativo.
