#!/usr/bin/env sh
export MSYS_NO_PATHCONV=1  # Git Bash convierte /paths a rutas de Windows; no aplica en Linux/Mac
# Escenario servicio_detenido: para el contenedor checkout. ServiceDown se dispara
# (up{job="checkout"} = 0). Recuperar: make recuperar-servicio.
set -e
docker compose stop checkout
echo "checkout detenido. Esperar ~30s y revisar Grafana/aiops."
