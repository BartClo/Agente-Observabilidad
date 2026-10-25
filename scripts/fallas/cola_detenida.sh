#!/usr/bin/env sh
export MSYS_NO_PATHCONV=1  # Git Bash convierte /paths a rutas de Windows; no aplica en Linux/Mac
# Escenario cola_detenida (k3d): el consumidor simulado se desconecta de la cola. El proceso
# sigue vivo pero su metrica pasa a rabbitmq_queue_consumers{queue="worker"} = 0 -> QueueStalled.
# La accion autorizada restart_consumer (rollout restart) lo reconecta.
# Recuperar a mano: sh scripts/fallas/recuperar_cola.sh
set -e
sh "$(dirname "$0")/_k8s_un_pod.sh" worker  # nunca el pod viejo de un rollout
POD=$(kubectl -n aiops-lab get pods -l app=worker -o jsonpath='{.items[0].metadata.name}')
kubectl -n aiops-lab exec "$POD" -- sh -c 'printf "# TYPE rabbitmq_queue_consumers gauge\nrabbitmq_queue_consumers{queue=\"worker\"} 0\n" > /www/metrics; echo "ERROR worker: consumidor desconectado de la cola (0 consumidores)" > /proc/1/fd/1'
echo "consumidor desconectado en $POD. Revisar QueueStalled en Grafana (~20s)."
