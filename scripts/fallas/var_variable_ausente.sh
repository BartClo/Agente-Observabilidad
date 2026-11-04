#!/usr/bin/env sh
export MSYS_NO_PATHCONV=1  # Git Bash convierte /paths a rutas de Windows; no aplica en Linux/Mac
# Variante de servicio_detenido: falta una variable obligatoria. El contenedor vive pero no
# sirve; rollout restart no lo arregla. Revertir: rev_variable_ausente.sh
. "$(dirname "$0")/_ns.sh"
set -e
kubectl -n "$NS" set env deployment/checkout CHECKOUT_DB_URL-
kubectl -n "$NS" rollout status deployment/checkout --timeout=120s
sh "$(dirname "$0")/_k8s_un_pod.sh" checkout
echo "checkout sin CHECKOUT_DB_URL."
