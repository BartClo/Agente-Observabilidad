# Vuelve lab-web a su definicion sana (compose) entre corridas.
set -e
docker rm -f ia-factory-lab-web >/dev/null 2>&1 || true
docker compose --profile docker-lab up -d --no-deps lab-web >/dev/null
echo "lab-web restaurado."
