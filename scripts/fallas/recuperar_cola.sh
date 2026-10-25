#!/usr/bin/env sh
export MSYS_NO_PATHCONV=1  # Git Bash convierte /paths a rutas de Windows; no aplica en Linux/Mac
# Recupera cola_detenida: reinicia el consumidor simulado (lo mismo que hace la accion
# restart_consumer del agente). Uso a mano: sh scripts/fallas/recuperar_cola.sh
set -e
kubectl -n aiops-lab rollout restart deployment/worker
kubectl -n aiops-lab rollout status deployment/worker --timeout=120s
sh "$(dirname "$0")/_k8s_un_pod.sh" worker
echo "consumidor worker recuperado."
