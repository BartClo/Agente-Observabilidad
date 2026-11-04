#!/usr/bin/env sh
export MSYS_NO_PATHCONV=1  # Git Bash convierte /paths a rutas de Windows; no aplica en Linux/Mac
# Revierte var_imagen_inexistente.sh por completo.
. "$(dirname "$0")/_ns.sh"
set -e
kubectl -n "$NS" set image deployment/api api=busybox:1.36
kubectl -n "$NS" rollout status deployment/api --timeout=120s
sh "$(dirname "$0")/_k8s_un_pod.sh" api
echo "imagen de api restaurada."
