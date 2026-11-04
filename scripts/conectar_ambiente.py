"""Genera un BORRADOR de perfil leyendo las reglas de alerta y las metricas de un Prometheus o
del endpoint Prometheus de Grafana. Solo lee y solo escribe un archivo: el borrador sale con
`aprobado: false` y todo en observacion, asi que el agente se niega a cargarlo hasta que una
persona lo revise. Ver docs/ambientes.md.

    python -m scripts.conectar_ambiente --prometheus http://prom:9090 --entorno qa \\
        --salida perfiles/qa.yaml
    # Con Grafana: --reglas-url http://grafana:3000/api/prometheus/grafana/api/v1/rules

ponytail: emparejar alertas por palabras clave es una heuristica; acierta con nombres
habituales y el resto queda para el humano. Un LLM podria proponer mas, pero no hace falta aca.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

# categoria -> (palabras en el nombre de la alerta, runbook, accion, senal, consulta por metrica)
_PLANTILLAS: dict[str, dict[str, Any]] = {
    "pod_fallido": {
        "palabras": r"pod|crashloop|container",
        "runbook": "RB-003",
        "accion": "recreate_pod",
        "senal": ("pod_ready", ">=", 1),
        "metrica": "kube_pod_status_ready",
    },
    "cola_detenida": {
        "palabras": r"queue|cola|consumer|rabbit|kafka",
        "runbook": "RB-004",
        "accion": "restart_consumer",
        "senal": ("queue_consumers_active", ">=", 1),
        "metrica": "rabbitmq_queue_consumers",
    },
    "disco_lleno": {
        "palabras": r"disk|disco|filesystem|storage",
        "runbook": "RB-002",
        "accion": "compress_old_logs",
        "senal": ("disk_usage_percent", "<=", 85),
        "metrica": "node_filesystem_avail_bytes",
    },
    "certificado_por_vencer": {
        "palabras": r"cert|ssl|tls",
        "runbook": "RB-005",
        "accion": None,
        "senal": ("cert_days_remaining", ">=", 14),
        "metrica": "probe_ssl_earliest_cert_expiry",
    },
    "servicio_detenido": {  # al final: "down" y "service" tambien aparecen en otras
        "palabras": r"down|caid|unavailable|service|servicio",
        "runbook": "RB-001",
        "accion": "restart_service",
        "senal": ("up", ">=", 1),
        "metrica": "up",
    },
}

Leer = Callable[[str], Any]


def _leer_http(url: str) -> Any:
    encabezados = {"Authorization": a} if (a := os.environ.get("AIOPS_PROMETHEUS_AUTH")) else {}
    pedido = urllib.request.Request(url, headers=encabezados)  # noqa: S310
    with urllib.request.urlopen(pedido, timeout=15) as r:  # noqa: S310
        return json.load(r)


def _alertas(reglas: Any) -> list[str]:
    nombres = {
        str(regla["name"])
        for grupo in reglas.get("data", {}).get("groups", [])
        for regla in grupo.get("rules", [])
        if regla.get("type", "alerting") == "alerting" and regla.get("name")
    }
    return sorted(nombres)


def borrador(entorno: str, reglas: Any, metricas: list[str]) -> tuple[dict[str, Any], list[str]]:
    """(perfil, avisos). Una categoria solo entra si su metrica existe en este ambiente: sin
    senal sana no se puede confirmar ni verificar nada."""
    por_categoria: dict[str, list[str]] = {c: [] for c in _PLANTILLAS}
    sin_categoria: list[str] = []
    for alerta in _alertas(reglas):
        for cid, p in _PLANTILLAS.items():
            if re.search(p["palabras"], alerta, re.IGNORECASE):
                por_categoria[cid].append(alerta)
                break
        else:
            sin_categoria.append(alerta)

    existentes = set(metricas)
    categorias: list[dict[str, Any]] = []
    avisos = [f"alerta sin categoria (se investiga sin actuar): {a}" for a in sin_categoria]
    for cid, alertas in por_categoria.items():
        if not alertas:
            continue
        p = _PLANTILLAS[cid]
        if p["metrica"] not in existentes:
            avisos.append(
                f"{cid}: no existe {p['metrica']}; falta una consulta. Alertas: {alertas}"
            )
            continue
        metrica, operador, umbral = p["senal"]
        categorias.append(
            {
                "id": cid,
                "alertas": alertas,
                "runbook": p["runbook"],
                "senal": {"metrica": metrica, "operador": operador, "umbral": umbral},
                "accion": p["accion"],
                "nivel": 1,  # observacion: subirlo es una decision humana, categoria por categoria
            }
        )
    perfil = {
        "version": 1,
        "aprobado": False,
        "aprobado_por": "",
        "entorno": entorno,
        "observabilidad": {"etiqueta_servicio": "service"},
        "categorias": categorias,
        "kubernetes": {"namespaces": []},
    }
    return perfil, avisos


def main(argv: list[str], leer: Leer = _leer_http) -> int:
    p = argparse.ArgumentParser(description="Genera un borrador de perfil de ambiente.")
    p.add_argument("--prometheus", required=True)
    p.add_argument("--reglas-url", default=None, help="por defecto, las reglas de Prometheus")
    p.add_argument("--entorno", required=True)
    p.add_argument("--salida", required=True)
    args = p.parse_args(argv)
    base = args.prometheus.rstrip("/")
    reglas = leer(args.reglas_url or f"{base}/api/v1/rules")
    metricas = leer(f"{base}/api/v1/label/__name__/values").get("data", [])
    perfil, avisos = borrador(args.entorno, reglas, metricas)
    salida = Path(args.salida)
    if salida.exists():
        # Nunca pisar un perfil que quiza ya fue aprobado.
        print(f"{salida} ya existe: no se sobrescribe", file=sys.stderr)
        return 1
    encabezado = "# BORRADOR: revisar y poner aprobado: true y aprobado_por para activarlo.\n"
    encabezado += "".join(f"# REVISAR: {a}\n" for a in avisos)
    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.write_text(
        encabezado + yaml.safe_dump(perfil, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    print(f"Borrador en {salida}: {len(perfil['categorias'])} categorias, {len(avisos)} avisos.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
