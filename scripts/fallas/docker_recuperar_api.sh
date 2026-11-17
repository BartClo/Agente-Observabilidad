# Docker: vuelve a sano ia-factory-lab-api entre corridas.
set -e
docker restart --time 5 ia-factory-lab-api >/dev/null
echo "ia-factory-lab-api reiniciado."
