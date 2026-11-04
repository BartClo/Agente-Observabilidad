#!/usr/bin/env sh
export MSYS_NO_PATHCONV=1  # Git Bash convierte /paths a rutas de Windows; no aplica en Linux/Mac
# Variante de pod_fallido: etiqueta de imagen que no existe. Evidencia: evento ImagePullBackOff
# (consultar_eventos). api usa strategy Recreate: el pod viejo no queda sano tapando la falla.
# Revertir: rev_imagen_inexistente.sh
. "$(dirname "$0")/_ns.sh"
set -e
kubectl -n "$NS" set image deployment/api api=busybox:no-existe-experimento
sh "$(dirname "$0")/_k8s_un_pod.sh" api
echo "api con imagen inexistente."
