#!/usr/bin/env sh
export MSYS_NO_PATHCONV=1  # Git Bash convierte /paths a rutas de Windows; no aplica en Linux/Mac
set -e
kubectl -n aiops-lab rollout undo deployment/api
echo "deployment api restaurado."
