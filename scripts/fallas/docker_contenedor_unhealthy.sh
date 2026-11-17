# Docker: el healthcheck empieza a fallar con el contenedor vivo (falta /tmp/ok).
set -e
docker exec ia-factory-lab-api rm -f /tmp/ok
echo "ia-factory-lab-api sin /tmp/ok: healthcheck fallando."
