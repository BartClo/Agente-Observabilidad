#!/usr/bin/env sh
export MSYS_NO_PATHCONV=1  # Git Bash convierte /paths a rutas de Windows; no aplica en Linux/Mac
# Variante de pod_fallido: configuracion invalida. Recrear el pod NO lo arregla: lee la misma
# configuracion. Revertir: rev_config_invalida.sh
. "$(dirname "$0")/_ns.sh"
set -e
kubectl -n "$NS" patch configmap api-config --type merge -p '{"data":{"modo":"invalido"}}'
kubectl -n "$NS" delete pod -l app=api
sh "$(dirname "$0")/_k8s_un_pod.sh" api
echo "api arranco con configuracion invalida."
