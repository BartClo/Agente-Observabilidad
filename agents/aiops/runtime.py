"""Arma el `Ciclo` del agente segun el entorno (AIOPS_*, ver .env.example).

Un unico `Ciclo` por proceso: es el estado del incidente que el agente mantiene entre
llamadas a tools. `reset()` existe para tests y evals.
"""

from __future__ import annotations

import os
from pathlib import Path

from domain.aiops_core.acciones import BackendAcciones, BackendDeshabilitado
from domain.aiops_core.auditoria import Auditoria
from domain.aiops_core.ciclo import Ciclo
from domain.aiops_core.observabilidad import ObservabilidadPort
from domain.aiops_core.politicas import politica_desde_entorno
from domain.aiops_core.simulador import EntornoSimulado

# Escenario de demo por defecto: un fallo de cada categoria del catalogo.
FALLOS_DEMO = (
    "servicio_detenido:checkout,disco_lleno:billing,pod_fallido:api,"
    "cola_detenida:worker,certificado_por_vencer:gateway"
)

_ciclo: Ciclo | None = None


def _armar() -> Ciclo:
    backend_nombre = os.environ.get("AIOPS_BACKEND", "simulado")
    observabilidad: ObservabilidadPort
    backend: BackendAcciones
    if backend_nombre == "simulado":
        env = EntornoSimulado(os.environ.get("AIOPS_SIM_ENV", "staging"))
        for item in (os.environ.get("AIOPS_SIM_FAULTS") or FALLOS_DEMO).split(","):
            if item.strip():
                categoria, servicio = item.strip().split(":", 1)
                env.inyectar_fallo(servicio, categoria)
        observabilidad, backend = env, env
    elif backend_nombre == "prometheus":
        from infra.observabilidad import PrometheusLoki

        observabilidad = PrometheusLoki.desde_entorno()
        # Sin backend real de acciones cableado: el agente observa, recomienda y escala.
        backend = BackendDeshabilitado()
    else:
        raise ValueError(f"AIOPS_BACKEND desconocido: {backend_nombre!r}")
    ruta = os.environ.get("AIOPS_AUDIT_FILE", "").strip()
    return Ciclo(
        observabilidad, backend, politica_desde_entorno(), Auditoria(Path(ruta) if ruta else None)
    )


def get_ciclo() -> Ciclo:
    global _ciclo
    if _ciclo is None:
        _ciclo = _armar()
    return _ciclo


def reset(ciclo: Ciclo | None = None) -> None:
    global _ciclo
    _ciclo = ciclo
