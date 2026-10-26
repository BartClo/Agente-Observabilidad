---
servicios: api, checkout
tipo: guia
vigente_desde: 2025-02-10
obsoleto: true
origen_dato: sintetico
---
# [OBSOLETO] Reinicio manual por SSH de api y checkout

> Este procedimiento quedó obsoleto cuando los servicios pasaron a Kubernetes. No usar.
> Vigente hasta 2025-11: sustituido por `kubectl rollout restart`.

1. Conectarse por SSH al servidor `app-01`.
2. Ejecutar `sudo systemctl restart api checkout`.
3. Esperar 30 segundos y comprobar `curl localhost:8080/health`.
4. Si no responde, reiniciar el servidor completo.

El paso 4 ya no aplica: reiniciar el servidor entero afecta a otros servicios y no hay
servidores `app-01` en el entorno actual.
