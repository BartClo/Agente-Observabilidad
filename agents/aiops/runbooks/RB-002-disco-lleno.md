---
id: RB-002
version: 1.0
categoria: disco_lleno
servicios: cualquiera del entorno autorizado
vigencia: PLACEHOLDER (validar con operaciones)
propietario: PLACEHOLDER
---

# RB-002 Uso anomalo de disco

**Condiciones de aplicacion:** alerta `DiskUsageHigh`, `disk_usage_percent > 85`,
crecimiento atribuible a logs rotados.

**Evidencia esperada:** uso de disco alto; directorio de logs con archivos
rotados sin comprimir.

**Accion autorizada:** `compress_old_logs` (comprime, no borra: es reversible).

**Verificacion:** `disk_usage_percent <= 85`.

**Rollback:** `restore_compressed_logs`.

**Escalar si:** el crecimiento viene de datos de la aplicacion (no logs), el
uso sigue alto tras comprimir, o el volumen es de base de datos.
