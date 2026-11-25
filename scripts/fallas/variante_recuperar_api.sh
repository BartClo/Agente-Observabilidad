# Vuelve lab-api a su definicion sana (compose) entre corridas.
set -e
docker rm -f ia-factory-lab-api >/dev/null 2>&1 || true
docker compose --profile docker-lab up -d --no-deps lab-api >/dev/null
echo "lab-api restaurado."
