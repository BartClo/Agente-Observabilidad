---
servicios:
tipo: arquitectura
vigente_desde: 2026-08-01
obsoleto: false
origen_dato: sintetico
---
# Arquitectura de la plataforma y su observabilidad

**Servicios de negocio.** `gateway` recibe el tráfico externo y lo reparte; `api` valida
pedidos; `checkout` cobra; `worker` procesa la cola; `billing` registra pagos. Todo corre
en un clúster Kubernetes (k3d en el laboratorio) en el namespace `aiops-lab`.

**Observabilidad.**
- Métricas: Prometheus (scrape cada 5 s) con kube-state-metrics y exporters por servicio.
- Logs: Promtail envía a Loki; se consultan por la etiqueta `service`.
- Alertas: Grafana evalúa las reglas cada 10 s y avisa solo en la transición a Alerting.

**Camino de una alerta.** Grafana dispara un webhook hacia la API de AIOps; la API
encola el trabajo en Redis (RQ) con el id de la alerta como identificador, así una alerta
repetida no duplica trabajo. Un worker toma el trabajo, abre el incidente, lo atiende y
deja el resultado y la línea de tiempo en Postgres.

**Reglas de seguridad.** Las acciones automáticas salen de una lista cerrada y
autorizada (reiniciar servicio, recrear pod, reiniciar consumidor, comprimir logs
antiguos). Existe un interruptor de emergencia (kill switch) que las detiene todas, un
umbral de confianza mínimo y un cortacircuito: tras 3 acciones sobre el mismo servicio en
una hora se deja de actuar y se escala a una persona.

**Qué no hace.** No toca bases de datos ni configuración de producción, no despliega
versiones y no borra datos.
