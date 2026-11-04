#!/usr/bin/env sh
export MSYS_NO_PATHCONV=1  # Git Bash convierte /paths a rutas de Windows; no aplica en Linux/Mac
# Variante de cola_detenida: mensaje malformado. La cola del consumidor simulado es un ConfigMap:
# el mensaje sobrevive al reinicio y restart_consumer no lo arregla.
# Revertir: rev_mensaje_venenoso.sh
. "$(dirname "$0")/_ns.sh"
set -e
kubectl -n "$NS" patch configmap worker-cola --type merge -p '{"data":{"siguiente":"msg-4711"}}'
kubectl -n "$NS" rollout restart deployment/worker
kubectl -n "$NS" rollout status deployment/worker --timeout=120s
sh "$(dirname "$0")/_k8s_un_pod.sh" worker
echo "mensaje venenoso publicado."
