# Variante confusora: el servicio se recrea sin una variable de entorno obligatoria.
set -e
docker rm -f ia-factory-lab-worker >/dev/null
docker run -d --init --name ia-factory-lab-worker --network agente-observabilidad-master_default busybox:1.36 sh -c '
echo "INFO  worker: iniciando"; sleep 1
[ -n "$DATABASE_URL" ] || { echo "FATAL worker: falta la variable de entorno obligatoria DATABASE_URL"; exit 1; }
' >/dev/null
echo "lab-worker recreado sin DATABASE_URL."
