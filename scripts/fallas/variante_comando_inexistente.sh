# Variante confusora (imagen inexistente de la Tabla 14, adaptada a Docker): el despliegue nuevo
# no puede arrancar porque la imagen no trae el ejecutable. docker run falla a proposito.
docker rm -f ia-factory-lab-api >/dev/null
docker run -d --init --name ia-factory-lab-api --entrypoint app-server busybox:1.36 >/dev/null 2>&1
docker inspect ia-factory-lab-api >/dev/null || exit 1
echo "lab-api recreado con una imagen sin el ejecutable."
