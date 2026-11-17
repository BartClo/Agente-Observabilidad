#!/usr/bin/env python3
"""Exportador de estado de contenedores del laboratorio Docker (solo stdlib, corre en el host).

Imita al docker-healthcheck-exporter de AI Factory: publica las mismas series para que el
perfil (perfiles/docker-lab.yaml) use las mismas consultas que en QA.
  iafactory_infra_container_state{service_name}          1 corriendo, 0 detenido
  iafactory_infra_container_health_status{service_name}  1 healthy, 0 unhealthy/detenido,
                                                          -1 sin healthcheck
Solo lee (`docker inspect`). Prometheus lo scrapea en host.docker.internal:9417.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PREFIJO = "ia-factory-"
SERVICIOS = os.environ.get("LAB_SERVICIOS", "lab-web,lab-api,lab-worker").split(",")
_metricas = ""


def leer(servicio: str) -> tuple[int, int]:
    r = subprocess.run(
        ["docker", "inspect", PREFIJO + servicio], capture_output=True, text=True, timeout=20
    )
    if r.returncode != 0:
        return 0, 0
    estado = json.loads(r.stdout)[0]["State"]
    corriendo = 1 if estado.get("Running") else 0
    salud = (estado.get("Health") or {}).get("Status")
    if not corriendo:
        return 0, 0
    if salud is None:
        return 1, -1
    return 1, 1 if salud == "healthy" else 0


def actualizar() -> None:
    global _metricas
    while True:
        lineas = []
        for s in SERVICIOS:
            try:
                est, salud = leer(s)
            except Exception:
                continue
            lineas.append(f'iafactory_infra_container_state{{service_name="{s}"}} {est}')
            lineas.append(f'iafactory_infra_container_health_status{{service_name="{s}"}} {salud}')
        _metricas = "\n".join(lineas) + "\n"
        time.sleep(2)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        cuerpo = _metricas.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.end_headers()
        self.wfile.write(cuerpo)

    def log_message(self, *_: object) -> None:
        pass


if __name__ == "__main__":
    threading.Thread(target=actualizar, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PUERTO", "9417"))), Handler).serve_forever()
