#!/usr/bin/env sh
export MSYS_NO_PATHCONV=1  # Git Bash convierte /paths a rutas de Windows; no aplica en Linux/Mac
# Escenario disco_lleno: llena el tmpfs de 50MB de billing hasta ~90% (umbral 85%).
# DiskUsageHigh se dispara. Recuperar: make recuperar-disco.
set -e
docker compose exec -T disco-billing-tools sh -c "dd if=/dev/zero of=/data/filler bs=1M count=45 2>/dev/null"
docker compose exec -T disco-billing-tools sh -c "df -h /data"
echo "disco billing lleno. Revisar DiskUsageHigh en Grafana."
