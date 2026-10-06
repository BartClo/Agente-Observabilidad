#!/usr/bin/env sh
export MSYS_NO_PATHCONV=1  # Git Bash convierte /paths a rutas de Windows; no aplica en Linux/Mac
set -e
kubectl -n aiops-lab delete pod -l app=api
sh "$(dirname "$0")/_k8s_un_pod.sh" api
echo "pod api recreado."
