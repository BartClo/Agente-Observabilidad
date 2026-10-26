---
servicios: checkout
tipo: postmortem
vigente_desde: 2026-03-14
obsoleto: false
origen_dato: sintetico
---
# Postmortem: checkout sin servicio por falta de memoria (2026-03-12)

**Resumen.** `checkout` dejó de responder durante 11 minutos en plena campaña. La alerta
`ServiceDown` se disparó a las 19:42.

**Impacto.** Unos 380 intentos de pago fallidos; ~9 % reintentó y completó la compra más
tarde. Consumió el 25 % del presupuesto de error del mes.

**Línea de tiempo.**
- 19:38 pico de tráfico por correo promocional.
- 19:42 `up{job="checkout"}` en 0; los logs mostraban `ERROR checkout: proceso terminado
  por señal 9` (OOM kill).
- 19:44 la guardia confirma que no hay despliegue en curso.
- 19:47 se reinicia el deployment (`rollout restart`).
- 19:53 `up` vuelve a 1 y la latencia se normaliza.

**Causa raíz.** El límite de memoria (256 Mi) era insuficiente para el pico de la campaña;
el kernel terminó el proceso.

**Qué funcionó.** Reiniciar el servicio lo recuperó de inmediato porque la causa era
agotamiento de recursos y no un defecto de código o configuración.

**Acciones.**
1. Subir el límite de memoria y vigilar el consumo (pendiente, ver `cambios-recientes.md`).
2. Avisar a Pagos antes de campañas de correo.
3. Evaluar un `livenessProbe` para que Kubernetes lo reinicie solo.

**Aprendizaje.** El reinicio fue correcto y suficiente aquí, pero no previene la
recurrencia mientras no se ajuste el límite.
