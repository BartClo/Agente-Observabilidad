---
servicios: api
tipo: postmortem
vigente_desde: 2026-04-22
obsoleto: false
origen_dato: sintetico
---
# Postmortem: api NotReady por un ConfigMap incorrecto (2026-04-20)

**Resumen.** Después de una actualización de configuración, el pod de `api` quedó NotReady
y la alerta `PodFailed` se disparó a las 10:15. Duró 47 minutos porque se recreó el pod
dos veces sin éxito.

**Impacto.** `api` sin pods listos: los pedidos nuevos fallaron en el gateway. Sin pérdida
de datos.

**Línea de tiempo.**
- 10:05 se aplica un cambio en el ConfigMap `api-config` (ruta del archivo de salud).
- 10:15 `kube_pod_status_ready` en 0; log `ERROR api: chequeo de salud fallando`.
- 10:18 se recrea el pod: arranca y vuelve a quedar NotReady.
- 10:31 segunda recreación, mismo resultado.
- 10:44 alguien nota que el cambio de las 10:05 apunta a una ruta que no existe.
- 10:52 se revierte el ConfigMap y el pod queda listo.

**Causa raíz.** El ConfigMap nuevo cambió la ruta que consulta el chequeo de salud. El pod
estaba sano; la configuración era la que fallaba.

**Qué no funcionó.** Recrear el pod: cada pod nuevo leía el mismo ConfigMap erróneo.

**Acciones.**
1. Validar los cambios de `api-config` antes de aplicarlos.
2. Ante un NotReady justo después de un cambio de configuración, revisar el cambio antes
   de recrear nada.

**Aprendizaje.** Si la falla coincide con un cambio reciente, recrear el pod no la
arregla. Hay que escalar al responsable del cambio.
