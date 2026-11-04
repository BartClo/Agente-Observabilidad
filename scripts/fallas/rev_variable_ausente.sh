#!/usr/bin/env sh
export MSYS_NO_PATHCONV=1  # Git Bash convierte /paths a rutas de Windows; no aplica en Linux/Mac
# Revierte var_variable_ausente.sh por completo.
. "$(dirname "$0")/_ns.sh"
set -e
kubectl -n "$NS" set env deployment/checkout CHECKOUT_DB_URL=db.lab:5432
kubectl -n "$NS" rollout status deployment/checkout --timeout=120s
sh "$(dirname "$0")/_k8s_un_pod.sh" checkout
echo "variable de checkout restaurada."
