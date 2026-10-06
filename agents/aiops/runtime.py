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
from domain.aiops_core.politicas import Politica, politica_desde_entorno
from domain.aiops_core.repositorio import RepositorioIncidentes
from domain.aiops_core.simulador import EntornoSimulado

# Escenario de demo por defecto: un fallo de cada categoria del catalogo.
FALLOS_DEMO = (
    "servicio_detenido:checkout,disco_lleno:billing,pod_fallido:api,"
    "cola_detenida:worker,certificado_por_vencer:gateway"
)

_ciclo: Ciclo | None = None


def armar(*, persistencia: str | None = None) -> Ciclo:
    """Arma un `Ciclo` nuevo. `persistencia` fuerza "memoria"/"postgres" para ESTE
    `Ciclo` sin tocar `AIOPS_PERSISTENCIA` del entorno (que es compartido por todo el
    proceso): lo usa `agents/aiops/worker_jobs.py`, que necesita Postgres para su
    propio trabajo sin pisarle el entorno a quien mas corra en el mismo proceso (ver
    docs/plan-aiops.md Fase 2/3). `get_ciclo()` sigue siendo el singleton que lee el
    entorno; esta funcion no lo usa ni lo modifica."""
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
        acciones = os.environ.get("AIOPS_ACTIONS", "ninguna")
        if acciones == "k8s":
            from infra.acciones_k8s import BackendKubernetes

            backend = BackendKubernetes.desde_entorno()
        elif acciones == "ninguna":
            # Sin backend de acciones: el agente observa, recomienda y escala.
            backend = BackendDeshabilitado()
        else:
            raise ValueError(f"AIOPS_ACTIONS desconocido: {acciones!r}")
    else:
        raise ValueError(f"AIOPS_BACKEND desconocido: {backend_nombre!r}")

    politica = politica_desde_entorno()
    ruta = os.environ.get("AIOPS_AUDIT_FILE", "").strip()
    on_evento = None
    repositorio: RepositorioIncidentes | None = None
    # Default "memoria": no cambia el comportamiento de make aiops-demo/evals (que no
    # necesitan sobrevivir un reinicio). "postgres" lo activa la API de la Fase 2, que
    # si lo necesita (ver docs/plan-aiops.md Fase 1).
    if persistencia is None:
        persistencia = os.environ.get("AIOPS_PERSISTENCIA", "memoria")
    if persistencia == "postgres":
        from infra.auditoria_postgres import crear_sink_postgres
        from infra.incidentes_postgres import RepositorioIncidentesPostgres
        from infra.kill_switch import kill_switch_postgres

        repositorio = RepositorioIncidentesPostgres()
        on_evento = crear_sink_postgres()
        politica = Politica(
            nivel=politica.nivel,
            entornos_permitidos=politica.entornos_permitidos,
            servicios_permitidos=politica.servicios_permitidos,
            umbral_confianza=politica.umbral_confianza,
            max_reintentos=politica.max_reintentos,
            kill_switch=kill_switch_postgres(),
        )
    auditoria = Auditoria(Path(ruta) if ruta else None, on_evento=on_evento)
    return Ciclo(
        observabilidad,
        backend,
        politica,
        auditoria,
        repositorio=repositorio,
        verificacion_ventana_s=float(os.environ.get("AIOPS_VERIFY_WINDOW_S", "0")),
        verificacion_intervalo_s=float(os.environ.get("AIOPS_VERIFY_INTERVAL_S", "5")),
    )


def get_ciclo() -> Ciclo:
    """Singleton por proceso: el estado del incidente que el agente mantiene entre
    llamadas a tools, armado leyendo AIOPS_* del entorno. Para un Ciclo que no
    comparta ese singleton ni dependa del entorno ambiente, usar `armar()`."""
    global _ciclo
    if _ciclo is None:
        _ciclo = armar()
    return _ciclo


def reset(ciclo: Ciclo | None = None) -> None:
    global _ciclo
    _ciclo = ciclo
