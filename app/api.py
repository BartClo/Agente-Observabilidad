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
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse

from agents.aiops import runtime
from domain.aiops_core import metricas
from domain.aiops_core.ciclo import ErrorCiclo
from domain.aiops_core.modelos import Incidente
from infra import kill_switch
from infra.alertas_webhook import alerta_desde_grafana


async def _reintentar_avisos() -> None:
    """Mientras la API este arriba, entrega los avisos pendientes de Google Chat (los que
    fallaron al instante). Cada 30 s; un error aca nunca tumba la API."""
    import asyncio
    import logging

    from infra import notificaciones

    while True:
        await asyncio.sleep(30)
        url = os.environ.get("AIOPS_GCHAT_WEBHOOK_URL", "").strip()
        if not url or not os.environ.get("DATABASE_URL"):
            continue
        try:
            await asyncio.to_thread(notificaciones.entregar_pendientes, url, 20)
        except Exception:
            logging.getLogger(__name__).exception("reintento de avisos fallo")


@asynccontextmanager
async def _vida(_: FastAPI) -> AsyncIterator[None]:
    import asyncio

    tarea = asyncio.create_task(_reintentar_avisos())
    try:
        yield
    finally:
        tarea.cancel()


app = FastAPI(title="aiops API", lifespan=_vida)


def _verificar_token(variable: str, authorization: str | None) -> None:
    """La variable acepta varios tokens separados por coma: para rotar sin corte se
    agrega el nuevo, se actualizan los clientes (contact point de Grafana, operadores)
    y recien despues se quita el viejo. Comparacion en tiempo constante (hmac)."""
    validos = [t.strip() for t in os.environ.get(variable, "").split(",") if t.strip()]
    if not validos:
        raise HTTPException(500, f"{variable} no configurado")
    recibido = (authorization or "").encode()
    # Recorre todos sin cortar al primero que coincide: no filtra cual token es.
    if not any([hmac.compare_digest(recibido, f"Bearer {t}".encode()) for t in validos]):
        raise HTTPException(401, "token invalido o ausente")


def requiere_token(authorization: Annotated[str | None, Header()] = None) -> None:
    _verificar_token("AIOPS_API_TOKEN", authorization)


def requiere_admin(authorization: Annotated[str | None, Header()] = None) -> None:
    """Token aparte para configurar el LLM (API keys): el de operador (que tambien
    tiene Grafana para el webhook) no alcanza para cambiar credenciales."""
    _verificar_token("AIOPS_ADMIN_TOKEN", authorization)


_AUTENTICADO = [Depends(requiere_token)]
_ADMIN = [Depends(requiere_admin)]


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

    from rq import Retry

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
            # Fase 6: un job colgado (LLM sin responder) no bloquea al worker para
            # siempre; uno que falla (servicio ocupado, red) se reintenta con espera
            # creciente; agotados los reintentos queda en el FailedJobRegistry de RQ
            # (cola de fallidos) por AIOPS_JOB_FALLIDOS_TTL_S para revisarlo.
            job_timeout=int(os.environ.get("AIOPS_JOB_TIMEOUT_S", "900")),
            retry=Retry(max=int(os.environ.get("AIOPS_JOB_REINTENTOS", "2")), interval=[30, 120]),
            failure_ttl=int(os.environ.get("AIOPS_JOB_FALLIDOS_TTL_S", str(7 * 86400))),
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
        # Fase 7: lo que necesita scripts/experimento.py para medir MTTR y costo.
        "disparada_en": inc.alerta.disparada_en,
        "cerrado_en": inc.cerrado_en,
        "tokens_entrada": inc.tokens_entrada,
        "tokens_salida": inc.tokens_salida,
        "turnos_llm": inc.turnos_llm,
        "llamadas_tools": inc.llamadas_tools,
        "modelo_llm": inc.modelo_llm,
    }


@app.get("/incidentes", dependencies=_AUTENTICADO)
def listar_incidentes() -> list[dict[str, Any]]:
    return [_resumen(i) for i in runtime.get_ciclo().incidentes()]


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
        "fuentes_recuperadas": inc.fuentes_recuperadas,
        "fuentes_citadas": inc.fuentes_citadas,
        "motivo_escalamiento": inc.motivo_escalamiento,
        "acciones": [dataclasses.asdict(a) for a in inc.acciones],
        "aprobacion": dataclasses.asdict(inc.aprobacion) if inc.aprobacion else None,
        "linea_de_tiempo": [
            {"ts": e.ts, "tipo": e.tipo, "datos": e.datos} for e in runtime.eventos_de(incidente_id)
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


@app.get("/notificaciones", dependencies=_AUTENTICADO)
def estado_notificaciones() -> dict[str, Any]:
    """Estado de los avisos a Google Chat: configurado y cuantos hay pendientes,
    enviados y fallidos (agotaron los reintentos)."""
    from agents.aiops import notificaciones

    return notificaciones.estado()


@app.post("/notificaciones/probar", dependencies=_ADMIN)
def probar_notificaciones() -> dict[str, Any]:
    """Manda un mensaje de prueba al espacio de Google Chat (sin pasar por la bandeja)
    para validar el webhook. Admin: puede generar mensajes."""
    from infra import gchat

    url = os.environ.get("AIOPS_GCHAT_WEBHOOK_URL", "").strip()
    if not url:
        raise HTTPException(422, "AIOPS_GCHAT_WEBHOOK_URL no configurado")
    try:
        gchat.enviar(url, "🧪 *Prueba* de notificaciones del agente AIOps: el webhook funciona.")
    except gchat.ErrorGChat as exc:
        return {"ok": False, "detalle": str(exc)}
    return {"ok": True, "detalle": "mensaje enviado"}


@app.post("/reconciliar", dependencies=_AUTENTICADO)
def reconciliar() -> dict[str, list[str]]:
    """Cierra o escala los incidentes que quedaron a medias (ver Ciclo.reconciliar).
    Pensado para un cron externo; el worker tambien barre al recibir cada alerta."""
    from agents.aiops.worker_jobs import reconciliar_colgados

    return {"reconciliados": reconciliar_colgados(runtime.get_ciclo())}


@app.get("/metricas", dependencies=_AUTENTICADO)
def ver_metricas() -> dict[str, Any]:
    incidentes = runtime.get_ciclo().incidentes()
    resultado: dict[str, Any] = {"total_incidentes": len(incidentes)}
    for nombre, fn in (
        ("tra", metricas.tasa_resolucion_autonoma),
        ("mttr_segundos", metricas.mttr),
        ("tasa_rollback", metricas.tasa_rollback),
        ("tokens_por_incidente", metricas.tokens_por_incidente),
        ("turnos_por_incidente", metricas.turnos_por_incidente),
    ):
        try:
            resultado[nombre] = fn(incidentes)
        except ValueError:
            resultado[nombre] = None
    return resultado


def _metrica_jobs_fallidos() -> list[str]:
    """Tamano de la cola de fallidos del worker (Fase 6). Sin Redis (profile no
    levantado) se omite: /metrics no debe caerse por un componente opcional."""
    try:
        from rq.registry import FailedJobRegistry

        from infra.queue import get_queue

        n = len(FailedJobRegistry(queue=get_queue("aiops")))
    except Exception:
        return []
    return [
        "# HELP aiops_jobs_fallidos Jobs del worker que agotaron sus reintentos.",
        "# TYPE aiops_jobs_fallidos gauge",
        f"aiops_jobs_fallidos {n}",
    ]


def _metrica_notificaciones() -> list[str]:
    """Bandeja de avisos a Google Chat. Sin Postgres/tabla se omite (como los jobs)."""
    try:
        from infra import notificaciones

        n = notificaciones.conteos()
    except Exception:
        return []
    return [
        "# HELP aiops_notificaciones Avisos a Google Chat por estado.",
        "# TYPE aiops_notificaciones gauge",
        *(f'aiops_notificaciones{{estado="{e}"}} {c}' for e, c in sorted(n.items())),
    ]


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
    lineas += _metrica_jobs_fallidos()
    lineas += _metrica_notificaciones()
    lineas += [
        "# HELP aiops_tokens_llm_total Tokens del LLM gastados atendiendo incidentes.",
        "# TYPE aiops_tokens_llm_total counter",
        f'aiops_tokens_llm_total{{tipo="entrada"}} {sum(i.tokens_entrada for i in incidentes)}',
        f'aiops_tokens_llm_total{{tipo="salida"}} {sum(i.tokens_salida for i in incidentes)}',
    ]
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


# --- Configuracion del LLM (infra/llm_config.py): proveedor, modelo y API key -------


def _config_llm(fn: Any, *args: Any) -> Any:
    from infra.llm_config import ConfigLLMError

    try:
        return fn(*args)
    except ConfigLLMError as exc:
        raise HTTPException(422, str(exc)) from exc


def _usuario(body: dict[str, Any]) -> str:
    usuario = body.get("usuario")
    if not isinstance(usuario, str) or not usuario:
        raise HTTPException(422, "falta 'usuario'")
    return usuario


@app.get("/config/llm", dependencies=_ADMIN)
def ver_config_llm() -> dict[str, Any]:
    """Proveedores, si tienen key (solo los ultimos 4 caracteres) y el modelo activo.
    Nunca devuelve una API key."""
    from infra import llm_config

    return llm_config.estado()


@app.put("/config/llm/credenciales/{proveedor}", dependencies=_ADMIN)
def guardar_credencial_llm(proveedor: str, body: dict[str, Any]) -> dict[str, Any]:
    from infra import llm_config

    api_key = body.get("api_key")
    if not isinstance(api_key, str):
        raise HTTPException(422, "falta 'api_key'")
    _config_llm(llm_config.guardar_api_key, proveedor, api_key, _usuario(body))
    return llm_config.estado()


@app.delete("/config/llm/credenciales/{proveedor}", dependencies=_ADMIN)
def borrar_credencial_llm(proveedor: str, usuario: str) -> dict[str, Any]:
    from infra import llm_config

    _config_llm(llm_config.borrar_api_key, proveedor, usuario)
    return llm_config.estado()


@app.put("/config/llm/activo", dependencies=_ADMIN)
def seleccionar_llm(body: dict[str, Any]) -> dict[str, Any]:
    """`{"proveedor": null}` vuelve al modelo por defecto (agent.yaml)."""
    from infra import llm_config

    _config_llm(llm_config.seleccionar, body.get("proveedor"), body.get("modelo"), _usuario(body))
    return llm_config.estado()


@app.put("/config/llm/respaldo", dependencies=_ADMIN)
def seleccionar_respaldo_llm(body: dict[str, Any]) -> dict[str, Any]:
    """Modelo que retoma el incidente si el principal falla. `{"proveedor": null}` lo quita."""
    from infra import llm_config

    _config_llm(
        llm_config.seleccionar_respaldo, body.get("proveedor"), body.get("modelo"), _usuario(body)
    )
    return llm_config.estado()


@app.post("/config/llm/probar", dependencies=_ADMIN)
def probar_llm(body: dict[str, Any]) -> dict[str, Any]:
    from infra import llm_config

    proveedor, modelo = body.get("proveedor"), body.get("modelo")
    if not isinstance(proveedor, str) or not isinstance(modelo, str):
        raise HTTPException(422, "faltan 'proveedor' y 'modelo'")
    ok, detalle = _config_llm(llm_config.probar, proveedor, modelo)
    return {"ok": ok, "detalle": detalle}


# --- Chat de consulta (agents/aiops/chat.py): SOLO LECTURA, no ejecuta nada -------

_MAX_MENSAJE = 4000


@app.post("/chat", dependencies=_AUTENTICADO)
def chat(body: dict[str, Any]) -> dict[str, str]:
    import re

    from agents.aiops import chat as chat_aiops
    from app.main import modelo_de_la_ui

    conversacion, mensaje = body.get("conversacion"), body.get("mensaje")
    if not isinstance(conversacion, str) or not re.fullmatch(r"[A-Za-z0-9-]{8,64}", conversacion):
        raise HTTPException(422, "'conversacion' invalida")
    if not isinstance(mensaje, str) or not mensaje.strip() or len(mensaje) > _MAX_MENSAJE:
        raise HTTPException(422, f"'mensaje' vacio o de mas de {_MAX_MENSAJE} caracteres")
    activo = modelo_de_la_ui()
    try:
        respuesta = chat_aiops.responder(
            conversacion, mensaje.strip(), activo[0] if activo else None
        )
    except Exception as exc:  # proveedor caido, key invalida: error legible, no un 500 mudo
        raise HTTPException(
            502,
            f"el modelo no respondio ({type(exc).__name__}): revisar el modelo y la API key "
            "en 'Modelo del agente'",
        ) from exc
    return {"respuesta": respuesta}


@app.get("/eventos", dependencies=_AUTENTICADO)
def eventos_recientes(desde: float = 0, limite: int = 50) -> list[dict[str, Any]]:
    """Feed de lo que hizo el agente (avisos del chat): eventos de auditoria posteriores
    a `desde` (epoch), sin pasar por el LLM. Solo en modo postgres (la auditoria del
    worker vive ahi); en memoria devuelve lo que vio este proceso."""
    limite = max(1, min(limite, 200))
    if os.environ.get("AIOPS_PERSISTENCIA") == "postgres":
        import psycopg

        with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
            filas = conn.execute(
                "SELECT ts, incidente_id, tipo, datos FROM aiops_eventos_auditoria "
                "WHERE ts > to_timestamp(%s) AND incidente_id <> 'config:llm' "
                "ORDER BY ts DESC LIMIT %s",
                (desde, limite),
            ).fetchall()
        eventos = [
            {"ts": ts.timestamp(), "incidente": i, "tipo": t, "datos": d} for ts, i, t, d in filas
        ]
    else:
        eventos = [
            {"ts": e.ts, "incidente": e.incidente_id, "tipo": e.tipo, "datos": e.datos}
            for e in runtime.get_ciclo().auditoria.eventos
            if e.ts > desde
        ][-limite:][::-1]
    return eventos[::-1]  # mas viejo primero, para agregarlos en orden
