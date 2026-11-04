#!/usr/bin/env sh
export MSYS_NO_PATHCONV=1  # Git Bash convierte /paths a rutas de Windows; no aplica en Linux/Mac
# Revierte var_mensaje_venenoso.sh por completo: saca el mensaje y reinicia el consumidor.
. "$(dirname "$0")/_ns.sh"
set -e
kubectl -n "$NS" patch configmap worker-cola --type merge -p '{"data":{"siguiente":""}}'
kubectl -n "$NS" rollout restart deployment/worker
kubectl -n "$NS" rollout status deployment/worker --timeout=120s
sh "$(dirname "$0")/_k8s_un_pod.sh" worker
echo "cola limpia."
