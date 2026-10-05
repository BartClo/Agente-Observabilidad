#!/usr/bin/env sh
export MSYS_NO_PATHCONV=1  # Git Bash convierte /paths a rutas de Windows; no aplica en Linux/Mac
set -e
docker compose exec -T disco-billing-tools rm -f /data/filler
echo "disco billing liberado."
