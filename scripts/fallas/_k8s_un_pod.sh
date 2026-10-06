#!/usr/bin/env sh
# Espera a que el Deployment tenga UN solo pod (sin el viejo terminando). Despues de un
# rollout, el pod viejo sigue apareciendo un rato; si un script de falla elige ese
# (items[0]), inyecta la falla en el pod equivocado. Uso: _k8s_un_pod.sh <app>
APP="$1"
i=0
while [ "$(kubectl -n aiops-lab get pods -l app="$APP" --no-headers 2>/dev/null | grep -c .)" != "1" ]; do
  i=$((i + 1))
  [ "$i" -gt 60 ] && { echo "timeout esperando un solo pod de $APP" >&2; exit 1; }
  sleep 3
done
