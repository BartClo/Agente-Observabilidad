#!/usr/bin/env sh
export MSYS_NO_PATHCONV=1  # Git Bash convierte /paths a rutas de Windows; no aplica en Linux/Mac
# Escenario pod_fallido (k3d): el Deployment api arranca un proceso que falla
# (CrashLoopBackOff). kube_pod_status_ready{condition="true"} = 0 -> PodFailed.
# Recuperar: make recuperar-pod (rollback del Deployment).
set -e
kubectl -n aiops-lab patch deployment/api --type=json \
  -p='[{"op":"replace","path":"/spec/template/spec/containers/0/command","value":["/bin/false"]}]'
echo "pod api en CrashLoop. Revisar PodFailed en Grafana (espera ~20s)."
