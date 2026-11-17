# Docker: el servidor deja de responder pero el contenedor sigue corriendo.
set -e
docker exec ia-factory-lab-worker pkill httpd
echo "httpd de ia-factory-lab-worker terminado: no responde."
