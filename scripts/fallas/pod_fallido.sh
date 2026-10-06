#!/usr/bin/env sh
export MSYS_NO_PATHCONV=1  # Git Bash convierte /paths a rutas de Windows; no aplica en Linux/Mac
# Escenario pod_fallido (k3d): borra /tmp/ok dentro del pod api. El pod sigue
# existiendo pero el readinessProbe falla -> kube_pod_status_ready{condition="true"}=0
# -> PodFailed. La accion autorizada recreate_pod lo arregla (el pod nuevo recrea
# /tmp/ok). Recuperar a mano: make recuperar-pod.
set -e
sh "$(dirname "$0")/_k8s_un_pod.sh" api  # nunca el pod viejo de un rollout
POD=$(kubectl -n aiops-lab get pods -l app=api -o jsonpath='{.items[0].metadata.name}')
kubectl -n aiops-lab exec "$POD" -- rm -f /tmp/ok
echo "pod $POD NotReady. Revisar PodFailed en Grafana (~20s)."
