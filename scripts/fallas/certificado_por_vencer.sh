#!/usr/bin/env sh
export MSYS_NO_PATHCONV=1  # Git Bash convierte /paths a rutas de Windows; no aplica en Linux/Mac
# Escenario certificado_por_vencer: el certificado de gateway vence en <14 dias
# (ver docker/nginx/certs/, generado con -days 3). CertExpiringSoon ya esta activo
# con el stack levantado. Regenerar cert: ver k8s-lab/README.md.
set -e
docker compose exec -T blackbox-exporter wget -qO- "http://localhost:9115/probe?target=https://gateway/&module=http_2xx" | grep probe_ssl_earliest_cert_expiry
echo "certificado de gateway vence pronto. Revisar CertExpiringSoon en Grafana."
