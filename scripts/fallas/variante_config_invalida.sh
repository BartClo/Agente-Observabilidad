# Variante confusora: el servicio se recrea con una configuracion invalida y muere al arrancar.
set -e
docker rm -f ia-factory-lab-web >/dev/null
docker run -d --init --name ia-factory-lab-web busybox:1.36 sh -c '
echo "INFO  app: iniciando, leyendo /etc/app/app.yaml"; sleep 1
echo "FATAL app: /etc/app/app.yaml linea 12: valor invalido para server.port: \"80x80\" (se esperaba un entero)"
exit 1' >/dev/null
echo "lab-web recreado con configuracion invalida."
