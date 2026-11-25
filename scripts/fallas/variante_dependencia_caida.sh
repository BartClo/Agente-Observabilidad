# Variante confusora (reemplaza "mensaje venenoso", sin cola en el perfil Docker): el servicio
# esta vivo pero responde error porque su base de datos no acepta conexiones.
set -e
docker rm -f ia-factory-lab-worker >/dev/null
docker run -d --init --name ia-factory-lab-worker --network agente-observabilidad-master_default busybox:1.36 sh -c '
echo "INFO  worker: iniciando, escuchando en 8080"
mkdir -p /www && httpd -p 8080 -h /www
while true; do
  echo "ERROR worker: no se pudo conectar a postgres-lab:5432: Connection refused"
  echo "WARN  worker: GET / -> 404, sin datos que servir"
  sleep 5
done' >/dev/null
echo "lab-worker sin su dependencia."
