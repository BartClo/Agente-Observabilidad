"""API HTTP del agente aiops (Fase 2 de docs/plan-aiops.md).

No ejecuta el agente inline salvo el webhook, que solo encola (ver
agents/aiops/worker_jobs.py); el resto son operaciones de lectura/escritura directas
sobre domain/aiops_core via agents.aiops.runtime.get_ciclo().

El kill switch (`/kill-switch`) siempre lee/escribe la tabla Postgres
(`infra/kill_switch.py`), sin importar `AIOPS_PERSISTENCIA`: Postgres no es opcional
en este proyecto (a diferencia de Redis/Qdrant), y el control-plane de la API tiene
que ser la misma fuente de verdad para todos los procesos. Solo gobierna la politica
de un `Ciclo` que corra con `AIOPS_PERSISTENCIA=postgres` (ver runtime.py): en modo
"memoria" (demo/evals) el kill switch sigue siendo el de variable de entorno/archivo.
"""

from __future__ import annotations

import dataclasses
import hmac
import os
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse

from agents.aiops import runtime
from domain.aiops_core import metricas
from domain.aiops_core.auditoria import Evento
from domain.aiops_core.ciclo import ErrorCiclo
from domain.aiops_core.modelos import Incidente
from infra import kill_switch
from infra.alertas_webhook import alerta_desde_grafana

app = FastAPI(title="aiops API")


def requiere_token(authorization: Annotated[str | None, Header()] = None) -> None:
    """AIOPS_API_TOKEN acepta varios tokens separados por coma: para rotar sin corte se
    agrega el nuevo, se actualizan los clientes (contact point de Grafana, operadores)
    y recien despues se quita el viejo. Comparacion en tiempo constante (hmac)."""
    validos = [t.strip() for t in os.environ.get("AIOPS_API_TOKEN", "").split(",") if t.strip()]
    if not validos:
        raise HTTPException(500, "AIOPS_API_TOKEN no configurado")
    recibido = (authorization or "").encode()
    # Recorre todos sin cortar al primero que coincide: no filtra cual token es.
    if not any([hmac.compare_digest(recibido, f"Bearer {t}".encode()) for t in validos]):
        raise HTTPException(401, "token invalido o ausente")


_AUTENTICADO = [Depends(requiere_token)]


@app.get("/salud")
def salud() -> dict[str, str]:
    return {"estado": "ok"}


_UI = Path(__file__).parent / "ui" / "index.html"


@app.get("/ui", response_class=HTMLResponse)
def ui() -> HTMLResponse:
    """UI para operar incidentes (Fase 5), pensada para embeberse en Grafana. Sin token:
    la pagina no trae datos; los pide a la API con el token que el operador ingresa
    (sessionStorage), en cabecera Authorization -- no cookie, asi que no hay CSRF.
    `frame-ancestors` limita quien la puede embeber (AIOPS_UI_FRAME_ANCESTORS)."""
    ancestros = os.environ.get("AIOPS_UI_FRAME_ANCESTORS", "'self' http://localhost:3001")
    csp = (
        "default-src 'self'; script-src 'self' 'unsafe-inline'; "
        f"style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors {ancestros}"
    )
    return HTMLResponse(_UI.read_text(encoding="utf-8"), headers={"Content-Security-Policy": csp})


@app.post("/webhooks/grafana", dependencies=_AUTENTICADO)
def webhook_grafana(payload: dict[str, Any]) -> dict[str, Any]:
    """Contact point tipo webhook de Grafana: `payload["alerts"]` trae una o varias
    alertas (firing o resolved). Solo valida, parsea y encola -- nunca ejecuta el
    agente inline (ver agents/aiops/worker_jobs.py, que corre en el servicio `worker`,
    profile `redis`). Dedupe por job_id = alerta.id (que ya incluye fingerprint/startsAt,
    distinto por cada disparo real: ver infra/alertas_webhook.py)."""
    import dataclasses as dc
    import re

    from infra.queue import get_queue

    etiqueta = os.environ.get("AIOPS_SERVICE_LABEL", "service")
    cola = get_queue("aiops")
    encolados: list[str] = []
    deduplicados: list[str] = []
    for item in payload.get("alerts", []):
        alerta, es_firing = alerta_desde_grafana(item, etiqueta)
        # RQ solo acepta [A-Za-z0-9_-] en job_id; alerta.id trae ":" (separador de
        # infra/alertas_webhook.py). No afecta el dedupe: sigue siendo 1 a 1 con
        # alerta.id, solo cambia el caracter separador.
        job_id = "aiops-webhook-" + re.sub(r"[^A-Za-z0-9_-]", "_", alerta.id)
        job = cola.fetch_job(job_id)
        if job is not None and job.get_status() in ("queued", "started", "deferred", "scheduled"):
            deduplicados.append(alerta.id)
            continue
        cola.enqueue(
            "agents.aiops.worker_jobs.procesar_alerta_webhook",
            dc.asdict(alerta),
            es_firing,
            job_id=job_id,
        )
        encolados.append(alerta.id)
    return {"encolados": encolados, "deduplicados": deduplicados}


def _resumen(inc: Incidente) -> dict[str, Any]:
    return {
        "id": inc.id,
        "estado": inc.estado,
        "servicio": inc.alerta.servicio,
        "entorno": inc.alerta.entorno,
        "alerta": inc.alerta.nombre,
        "categoria": inc.categoria_id,
        "elegible": inc.elegible,
        "verificado": inc.verificado,
        "resuelto_autonomo": inc.resuelto_autonomo,
        "intervencion_humana": inc.intervencion_humana,
        "aprobacion": inc.aprobacion.veredicto if inc.aprobacion else None,
        "abierto_en": inc.abierto_en,
    }


@app.get("/incidentes", dependencies=_AUTENTICADO)
def listar_incidentes() -> list[dict[str, Any]]:
    return [_resumen(i) for i in runtime.get_ciclo().incidentes()]


def _eventos_de(incidente_id: str) -> list[Evento]:
    # El proceso que atendio el incidente (el worker, ver worker_jobs.py) no es el
    # mismo que responde esta request (la API): Auditoria.eventos vive en memoria de
    # CADA proceso, asi que en modo postgres hay que releer desde ahi, no de
    # ciclo.auditoria (que solo tiene lo que vio ESTE proceso).
    if os.environ.get("AIOPS_PERSISTENCIA") == "postgres":
        from infra.auditoria_postgres import eventos_de_incidente

        return eventos_de_incidente(incidente_id)
    return runtime.get_ciclo().auditoria.de_incidente(incidente_id)


@app.get("/incidentes/{incidente_id}", dependencies=_AUTENTICADO)
def ver_incidente(incidente_id: str) -> dict[str, Any]:
    try:
        inc = runtime.get_ciclo().incidente(incidente_id)
    except ErrorCiclo as exc:
        raise HTTPException(404, str(exc)) from exc
    return {
        **_resumen(inc),
        "causa": inc.causa,
        "confianza": inc.confianza,
        "motivo_escalamiento": inc.motivo_escalamiento,
        "acciones": [dataclasses.asdict(a) for a in inc.acciones],
        "aprobacion": dataclasses.asdict(inc.aprobacion) if inc.aprobacion else None,
        "linea_de_tiempo": [
            {"ts": e.ts, "tipo": e.tipo, "datos": e.datos} for e in _eventos_de(incidente_id)
        ],
    }


@app.post("/incidentes/{incidente_id}/aprobar", dependencies=_AUTENTICADO)
def aprobar_incidente(incidente_id: str, body: dict[str, str]) -> dict[str, str]:
    usuario = body.get("usuario")
    if not usuario:
        raise HTTPException(422, "falta 'usuario'")
    try:
        runtime.get_ciclo().aprobar(incidente_id, usuario)
    except ErrorCiclo as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"estado": "aprobado"}


@app.post("/incidentes/{incidente_id}/rechazar", dependencies=_AUTENTICADO)
def rechazar_incidente(incidente_id: str, body: dict[str, str]) -> dict[str, str]:
    usuario, motivo = body.get("usuario"), body.get("motivo", "")
    if not usuario:
        raise HTTPException(422, "falta 'usuario'")
    try:
        paquete = runtime.get_ciclo().rechazar(incidente_id, usuario, motivo)
    except ErrorCiclo as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"estado": "rechazado", "paquete": paquete}


@app.get("/kill-switch", dependencies=_AUTENTICADO)
def leer_kill_switch() -> dict[str, Any]:
    return {"activo": kill_switch.leer()}


@app.post("/kill-switch", dependencies=_AUTENTICADO)
def cambiar_kill_switch(body: dict[str, Any]) -> dict[str, Any]:
    usuario = body.get("usuario")
    if not usuario:
        raise HTTPException(422, "falta 'usuario'")
    if body.get("activo"):
        kill_switch.activar(usuario, body.get("motivo", ""))
    else:
        kill_switch.desactivar(usuario)
    return {"activo": kill_switch.leer()}


@app.get("/metricas", dependencies=_AUTENTICADO)
def ver_metricas() -> dict[str, Any]:
    incidentes = runtime.get_ciclo().incidentes()
    resultado: dict[str, Any] = {"total_incidentes": len(incidentes)}
    for nombre, fn in (
        ("tra", metricas.tasa_resolucion_autonoma),
        ("mttr_segundos", metricas.mttr),
        ("tasa_rollback", metricas.tasa_rollback),
    ):
        try:
            resultado[nombre] = fn(incidentes)
        except ValueError:
            resultado[nombre] = None
    return resultado


@app.get("/metrics", response_class=PlainTextResponse)
def metricas_prometheus() -> str:
    """Formato de exposicion de Prometheus (no requiere token: es lo que el propio
    Prometheus/Grafana scrapea). Ver docs/plan-aiops.md Fase 2."""
    incidentes = runtime.get_ciclo().incidentes()
    lineas = [
        "# HELP aiops_incidentes_total Incidentes por estado.",
        "# TYPE aiops_incidentes_total gauge",
    ]
    por_estado: dict[str, int] = {}
    for i in incidentes:
        por_estado[str(i.estado)] = por_estado.get(str(i.estado), 0) + 1
    for estado, n in sorted(por_estado.items()):
        lineas.append(f'aiops_incidentes_total{{estado="{estado}"}} {n}')
    lineas += [
        "# HELP aiops_acciones_total Acciones ejecutadas.",
        "# TYPE aiops_acciones_total gauge",
    ]
    por_accion: dict[tuple[str, bool], int] = {}
    for i in incidentes:
        for a in i.acciones:
            por_accion[(a.nombre, a.ok)] = por_accion.get((a.nombre, a.ok), 0) + 1
    for (accion, ok), n in sorted(por_accion.items()):
        lineas.append(f'aiops_acciones_total{{accion="{accion}",ok="{str(ok).lower()}"}} {n}')
    tra_help = "Tasa de resolucion autonoma (0 a 100)."
    for nombre, help_, fn in (
        ("aiops_tra_ratio", tra_help, metricas.tasa_resolucion_autonoma),
        ("aiops_mttr_seconds", "MTTR en segundos.", metricas.mttr),
    ):
        lineas.append(f"# HELP {nombre} {help_}")
        lineas.append(f"# TYPE {nombre} gauge")
        try:
            lineas.append(f"{nombre} {fn(incidentes)}")
        except ValueError:
            pass
    return "\n".join(lineas) + "\n"
