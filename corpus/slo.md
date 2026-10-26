---
servicios:
tipo: guia
vigente_desde: 2026-07-01
obsoleto: false
origen_dato: sintetico
---
# Objetivos de nivel de servicio (SLO)

| Servicio | Disponibilidad mensual | Latencia p95 | Presupuesto de error |
|---|---|---|---|
| checkout | 99,9 % | 400 ms | 43 min/mes |
| api | 99,9 % | 250 ms | 43 min/mes |
| worker | 99,5 % | n/a (asíncrono) | 3,6 h/mes |
| billing | 99,95 % | 300 ms | 22 min/mes |
| gateway | 99,95 % | 100 ms | 22 min/mes |

**Cómo se mide.** La disponibilidad sale de la métrica `up` de cada servicio y, para `api`,
de los pods listos (`kube_pod_status_ready`). El tiempo de una caída cuenta desde que la
alerta se dispara hasta que la métrica vuelve a estar sana.

**Uso del presupuesto de error.** Si un servicio consumió más de la mitad de su presupuesto
en el mes, se congelan los despliegues no urgentes hasta el mes siguiente. Un incidente
resuelto en menos de 5 minutos casi nunca compromete el SLO; los que se repiten sí.

**Nota.** El `worker` tiene un objetivo menor porque la cola absorbe interrupciones breves:
los pedidos se procesan más tarde, no se pierden.
