# Vuelve lab-worker a su definicion sana (compose) entre corridas.
set -e
docker rm -f ia-factory-lab-worker >/dev/null 2>&1 || true
docker compose --profile docker-lab up -d --no-deps lab-worker >/dev/null
echo "lab-worker restaurado."
