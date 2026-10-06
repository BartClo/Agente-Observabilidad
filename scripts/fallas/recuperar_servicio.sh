#!/usr/bin/env sh
export MSYS_NO_PATHCONV=1  # Git Bash convierte /paths a rutas de Windows; no aplica en Linux/Mac
set -e
kubectl -n aiops-lab rollout restart deployment/checkout
kubectl -n aiops-lab rollout status deployment/checkout --timeout=120s
sh "$(dirname "$0")/_k8s_un_pod.sh" checkout
echo "checkout recuperado."
