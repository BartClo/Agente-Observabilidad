---
servicios: gateway
tipo: ficha
vigente_desde: 2026-07-15
obsoleto: false
origen_dato: sintetico
---
# Ficha de servicio: gateway

**Qué hace.** Punto de entrada del tráfico externo: termina TLS, aplica límites de
velocidad y enruta hacia `api` y `checkout`.

**Despliegue.** Dos réplicas detrás de un balanceador. El certificado TLS se renueva una
vez al año (ver `renovacion-certificados-tls.md`).

**Métricas clave.** `probe_success{service="gateway"}` del sondeo externo,
`probe_ssl_earliest_cert_expiry` para la fecha de vencimiento del certificado y la tasa de
errores 5xx.

**Alertas.** `CertExpiringSoon` (severidad media) cuando faltan menos de 15 días para que
venza el certificado.

**Dueño.** Equipo de Plataforma. Los cambios de certificado y de reglas de enrutamiento
los hace siempre una persona de Plataforma.
