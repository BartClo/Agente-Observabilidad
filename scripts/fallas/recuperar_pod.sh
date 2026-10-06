#!/usr/bin/env sh
export MSYS_NO_PATHCONV=1  # Git Bash convierte /paths a rutas de Windows; no aplica en Linux/Mac
set -e
kubectl -n aiops-lab delete pod -l app=api
echo "pod api recreado."
