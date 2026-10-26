---
servicios: api
tipo: postmortem
vigente_desde: 2026-06-12
obsoleto: false
origen_dato: sintetico
---
# Postmortem: api caída tras un despliegue defectuoso (2026-06-10)

**Resumen.** Tras desplegar la versión 2.3.0 de `api`, los pods quedaron NotReady. La
alerta `PodFailed` se disparó a las 15:03, 4 minutos después del despliegue.

**Impacto.** 22 minutos sin `api`. Los pedidos fallaron en el gateway; la campaña de la
tarde se retrasó.

**Línea de tiempo.**
- 14:59 se despliega 2.3.0.
- 15:03 `kube_pod_status_ready` en 0.
- 15:06 se recrea el pod; el nuevo pod vuelve a arrancar y a fallar el chequeo de salud.
- 15:12 el log de arranque muestra `FATAL api: variable DIRECCIONES_URL no definida`.
- 15:20 se revierte al deployment 2.2.4 (`kubectl rollout undo`).
- 15:25 pods listos.

**Causa raíz.** La versión 2.3.0 exigía una variable de entorno nueva que no estaba en el
manifiesto del despliegue.

**Qué no funcionó.** Recrear el pod: la imagen y el manifiesto eran los mismos.

**Acciones.**
1. Verificar variables obligatorias en la fase de despliegue previo.
2. El rollback del despliegue es el primer paso cuando el problema aparece justo después
   de publicar una versión.

**Aprendizaje.** Un pod que falla de nuevo apenas se recrea, con un error de arranque en
el log, indica un defecto de la versión. No es un fallo operativo recuperable reiniciando.
