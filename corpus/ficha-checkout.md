---
servicios: checkout
tipo: ficha
vigente_desde: 2026-07-15
obsoleto: false
origen_dato: sintetico
---
# Ficha de servicio: checkout

**Qué hace.** Servicio de cobro: confirma el carrito, calcula totales y llama a billing
para registrar el pago. Es el servicio con más impacto en ingresos.

**Despliegue.** Deployment `checkout` en el namespace `aiops-lab`, una réplica, servido
por `httpd` en el puerto 8080 y expuesto como NodePort 30081 para Prometheus. Se reinicia
con `kubectl -n aiops-lab rollout restart deployment/checkout`.

**Salud.** Prometheus lo scrapea en el job `checkout`; la métrica `up{job="checkout"}` es
1 cuando responde. No tiene `livenessProbe`: si el proceso del servidor termina, el
contenedor sigue vivo pero sin servir, y nadie lo reinicia automáticamente.

**Métricas clave.**
- `up{job="checkout"}`: disponibilidad (alerta `ServiceDown`, severidad alta, 10 s).
- Latencia p95 objetivo: 400 ms. Disponibilidad objetivo: 99,9 % mensual (ver `slo.md`).

**Logs.** `{service="checkout"}` en Loki. Un cierre abrupto deja una línea `ERROR` con la
señal recibida; un error de configuración deja `FATAL` al arrancar.

**Dependencias.** billing (pagos), base de datos de carritos, gateway aguas arriba.

**Dueño.** Equipo de Pagos. Escalar a su guardia si el servicio vuelve a caer tras
reiniciarlo, si hay `FATAL` de configuración o si billing también está degradado.

**Limitaciones conocidas.** Los picos de tráfico de campaña pueden agotar la memoria
(historial de OOM); reiniciar recupera el servicio pero no evita la recurrencia hasta
ajustar los límites. Un reinicio durante un despliegue en curso puede dejar versiones
mezcladas.
