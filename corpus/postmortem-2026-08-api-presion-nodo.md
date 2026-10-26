---
servicios: api
tipo: postmortem
vigente_desde: 2026-08-26
obsoleto: false
origen_dato: sintetico
---
# Postmortem: api NotReady por presión de memoria en el nodo (2026-08-24)

**Resumen.** El pod de `api` quedó NotReady a las 12:31 sin ningún cambio reciente. Se
resolvió recreándolo, en 3 minutos.

**Impacto.** Tres minutos sin pods listos; el gateway devolvió errores 503 a una fracción
del tráfico. Sin pérdida de datos.

**Línea de tiempo.**
- 12:30 el nodo reporta presión de memoria y desaloja procesos de baja prioridad.
- 12:31 `kube_pod_status_ready` en 0; `kubectl describe pod` muestra el chequeo de salud
  fallando y el contenedor sin memoria asignada de forma estable.
- 12:33 la guardia confirma que no hay despliegues ni cambios de configuración recientes.
- 12:34 se recrea el pod; el nuevo se programa en un nodo con memoria libre.
- 12:35 pod listo.

**Causa raíz.** Presión de memoria transitoria en el nodo (otro trabajo por lotes
consumía memoria).

**Qué funcionó.** Recrear el pod: al reprogramarse cayó en un nodo sano.

**Acciones.**
1. Separar los trabajos por lotes de los nodos de servicios de cara al cliente.
2. Añadir `requests` de memoria realistas al deployment.

**Aprendizaje.** Si no hay cambios recientes y los síntomas apuntan a recursos del nodo,
recrear el pod suele bastar. Si se repite, hay que investigar el nodo.
