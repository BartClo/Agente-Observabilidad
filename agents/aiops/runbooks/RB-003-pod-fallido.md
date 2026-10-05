---
id: RB-003
version: 1.0
categoria: pod_fallido
servicios: workloads con controlador (Deployment/StatefulSet)
vigencia: PLACEHOLDER (validar con operaciones)
propietario: PLACEHOLDER
---

# RB-003 Pod en estado fallido

**Condiciones de aplicacion:** alerta `PodCrashLooping` o `PodFailed`, pod
gestionado por un controlador que lo repone.

**Evidencia esperada:** `pod_ready == 0`; reinicios crecientes del contenedor.

**Accion autorizada:** `recreate_pod` (elimina el pod; el controlador crea uno nuevo).

**Verificacion:** `pod_ready >= 1`.

**Rollback:** no aplica.

**Escalar si:** el pod nuevo vuelve a fallar, la imagen o la configuracion
cambiaron recientemente, o el pod no tiene controlador.
