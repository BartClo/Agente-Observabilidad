---
servicios: gateway
tipo: guia
vigente_desde: 2026-09-12
obsoleto: false
origen_dato: sintetico
---
# Renovación de certificados TLS

**Quién.** Plataforma. La renovación no es automática en este entorno y nunca la hace un
proceso sin supervisión: un certificado mal instalado deja al gateway sin servicio.

**Cuándo.** La alerta `CertExpiringSoon` avisa con 15 días de margen. El certificado vigente
vence el 2027-09-12.

**Pasos.**
1. Solicitar el certificado nuevo a la autoridad certificadora con la solicitud de firma
   guardada en el gestor de secretos.
2. Instalarlo primero en una réplica del gateway y comprobar el sondeo externo.
3. Instalarlo en la segunda réplica.
4. Verificar que `probe_ssl_earliest_cert_expiry` refleja la nueva fecha.

**Riesgos.** Una cadena de certificados incompleta rompe a ciertos clientes antiguos. Hay
que probar con el sondeo desde fuera de la red.

**Escalamiento.** Si faltan menos de 3 días, tratar como severidad alta y avisar a la
jefatura de operaciones.
