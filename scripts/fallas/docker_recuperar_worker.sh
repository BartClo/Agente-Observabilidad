# Docker: vuelve a sano ia-factory-lab-worker entre corridas.
set -e
docker restart --time 5 ia-factory-lab-worker >/dev/null
echo "ia-factory-lab-worker reiniciado."
