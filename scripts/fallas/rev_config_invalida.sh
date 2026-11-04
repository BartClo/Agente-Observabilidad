#!/usr/bin/env sh
export MSYS_NO_PATHCONV=1  # Git Bash convierte /paths a rutas de Windows; no aplica en Linux/Mac
# Revierte var_config_invalida.sh por completo.
. "$(dirname "$0")/_ns.sh"
set -e
kubectl -n "$NS" patch configmap api-config --type merge -p '{"data":{"modo":"ok"}}'
kubectl -n "$NS" delete pod -l app=api
sh "$(dirname "$0")/_k8s_un_pod.sh" api
echo "configuracion de api restaurada."
