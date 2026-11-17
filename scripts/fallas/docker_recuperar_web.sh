# Docker: vuelve a sano ia-factory-lab-web entre corridas.
set -e
docker restart --time 5 ia-factory-lab-web >/dev/null
echo "ia-factory-lab-web reiniciado."
