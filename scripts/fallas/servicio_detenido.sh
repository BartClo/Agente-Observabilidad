#!/usr/bin/env sh
export MSYS_NO_PATHCONV=1  # Git Bash convierte /paths a rutas de Windows; no aplica en Linux/Mac
# Escenario servicio_detenido (k3d): mata httpd dentro del pod checkout. El contenedor
# sigue vivo (el proceso principal es un sleep) pero no sirve -> up{job="checkout"}=0
# -> ServiceDown. La accion autorizada restart_service (rollout restart) lo arregla.
# Recuperar a mano: make recuperar-servicio.
set -e
sh "$(dirname "$0")/_k8s_un_pod.sh" checkout  # nunca el pod viejo de un rollout
POD=$(kubectl -n aiops-lab get pods -l app=checkout -o jsonpath='{.items[0].metadata.name}')
# Por PID (guardado al arrancar, ver k8s-lab/workload-checkout.yaml).
kubectl -n aiops-lab exec "$POD" -- sh -c 'kill "$(cat /tmp/httpd.pid)"'
echo "httpd detenido en $POD. Revisar ServiceDown en Grafana (~20s)."
