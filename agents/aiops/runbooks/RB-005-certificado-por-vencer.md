---
id: RB-005
version: 1.0
categoria: certificado_por_vencer
servicios: endpoints TLS
vigencia: PLACEHOLDER (validar con operaciones)
propietario: PLACEHOLDER
---

# RB-005 Certificado proximo a vencer

**Condiciones de aplicacion:** alerta `CertExpiringSoon`, `cert_days_remaining < 14`.

**Evidencia esperada:** fecha de expiracion del certificado dentro de 14 dias.

**Accion autorizada:** ninguna. Caso de deteccion y escalamiento: la renovacion
toca secretos y no es una accion L1 autonoma.

**Verificacion:** no aplica.

**Escalar siempre** al equipo dueño del certificado, con dominio, dias
restantes y emisor.
