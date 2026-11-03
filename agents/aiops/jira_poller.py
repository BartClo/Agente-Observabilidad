"""Escucha un tablero de Jira y devuelve el resultado al ticket.

`sondear()` es un job de RQ que se re-agenda a si mismo cada `intervalo_s` (el worker corre
`--with-scheduler`). Cada sondeo:
1. publica los comentarios pendientes (bandeja = aiops_jira_tickets);
2. lee los tickets de la columna de entrada y encola los NUEVOS como alertas, por el mismo
   camino que el webhook de Grafana (`worker_jobs.encolar_alerta`). Cada ticket se procesa
   una sola vez (PK `clave`), aunque siga en la columna.

El sink de auditoria (`crear_sink`) marca el ticket `pendiente` cuando el incidente se
cierra, escala o descarta. El comentario sale de una plantilla, no del LLM. Si el
comentario se publico pero la transicion falla, NO se repite el comentario: el error queda
en `ultimo_error`. `AIOPS_JIRA=0` apaga todo (lo fija el experimento).
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import psycopg

from agents.aiops import jira_entrada
from domain.aiops_core.auditoria import Evento
from domain.aiops_core.modelos import Alerta, Incidente
from domain.aiops_core.saneamiento import sanear_linea
from infra.jira import ClienteJira, ErrorJira
from infra.jira_config import ConfigJira

logger = logging.getLogger(__name__)

MAX_POR_SONDEO = 5
MAX_INTENTOS = 8
_LEER_POR_SONDEO = 50  # ponytail: tickets vistos que siguen en la columna ocupan lugar; con
#                        mas de 50 viejos sin mover, filtrar por fecha en la JQL.
_CLAVE_PROXIMO = "aiops:jira:proximo"
_TERMINALES = {"cerrado": "resuelto", "escalado": "escalado", "descartado": "escalado"}
_PREFIJO = "INC-JIRA-"


def habilitado() -> bool:
    return os.environ.get("AIOPS_JIRA", "1") != "0"


def _url() -> str:
    return os.environ["DATABASE_URL"]


# --- puntos de inyeccion (los tests los reemplazan) -----------------------------------


def _cargar() -> ConfigJira | None:
    from infra import jira_config

    return jira_config.cargar()


def _cliente(cfg: ConfigJira) -> ClienteJira:
    return ClienteJira(cfg.sitio, cfg.correo, cfg.token)


def _clasificador() -> jira_entrada.Clasificador | None:
    try:
        return jira_entrada.clasificador_llm()
    except Exception:
        logger.exception("sin clasificador LLM para tickets de Jira")
        return None


def _encolar(alerta: Alerta) -> bool:
    from agents.aiops.worker_jobs import encolar_alerta

    return encolar_alerta(alerta, True)


def _registrar_sondeo(tickets: int, error: str | None) -> None:
    from infra import jira_config

    jira_config.registrar_sondeo(tickets, error)


def _agendar(segundos: float) -> None:
    from infra.queue import get_queue

    get_queue("aiops").enqueue_in(
        timedelta(seconds=segundos), "agents.aiops.jira_poller.sondear", job_timeout=120
    )


# --- sondeo -----------------------------------------------------------------------------


def programar(segundos: float | None = None) -> bool:
    """Agenda el proximo sondeo si Jira esta activo. Uno solo a la vez: una clave en Redis
    con TTL hace de candado (si el worker muere, vence y el arranque vuelve a agendar)."""
    if not habilitado():
        return False
    cfg = _cargar()
    if cfg is None or not cfg.activo:
        return False
    from infra.redis_client import get_redis

    espera = float(cfg.intervalo_s if segundos is None else segundos)
    if not get_redis().set(_CLAVE_PROXIMO, "1", nx=True, ex=int(espera) + 120):
        return False
    _agendar(espera)
    return True


def sondear() -> dict[str, Any]:
    """Job de RQ: un sondeo y, pase lo que pase, el siguiente."""
    from infra.redis_client import get_redis

    get_redis().delete(_CLAVE_PROXIMO)
    try:
        return _sondear()
    finally:
        try:
            programar()
        except Exception:
            logger.exception("no se pudo agendar el proximo sondeo de Jira")


def _sondear() -> dict[str, Any]:
    if not habilitado():
        return {"omitido": "AIOPS_JIRA=0"}
    cfg = _cargar()
    if cfg is None or not cfg.activo:
        return {"omitido": "inactivo"}
    cliente = _cliente(cfg)
    comentados = entregar_pendientes(cliente, cfg)
    try:
        tickets = cliente.tickets(cfg.tablero_id, cfg.entrada.estados, _LEER_POR_SONDEO)
    except ErrorJira as exc:
        _registrar_sondeo(0, str(exc))
        return {"error": str(exc), "comentados": comentados}
    nuevos: list[str] = []
    clasificador: jira_entrada.Clasificador | None = None
    for t in tickets:
        if len(nuevos) >= MAX_POR_SONDEO:
            break
        if not _tomar(t.clave):
            continue
        if clasificador is None and not ({"servicio", "categoria"} <= _prefijos(t.etiquetas)):
            clasificador = _clasificador()
        _encolar(jira_entrada.alerta_desde_ticket(t, clasificador))
        nuevos.append(t.clave)
    _registrar_sondeo(len(nuevos), None)
    return {"nuevos": nuevos, "comentados": comentados}


def _prefijos(etiquetas: tuple[str, ...]) -> set[str]:
    return {e.split(":", 1)[0].lower() for e in etiquetas if ":" in e}


def _tomar(clave: str) -> bool:
    """True si el ticket es nuevo (y queda registrado). Atomico: dos sondeos simultaneos no
    encolan el mismo ticket."""
    with psycopg.connect(_url(), autocommit=True) as conn:
        fila = conn.execute(
            "INSERT INTO aiops_jira_tickets (clave, incidente_id) VALUES (%s, %s) "
            "ON CONFLICT (clave) DO NOTHING RETURNING clave",
            (clave, f"{_PREFIJO}{clave}"),
        ).fetchone()
    return fila is not None


# --- escritura de vuelta ----------------------------------------------------------------


def comentario(tipo: str, datos: dict[str, Any], inc: Incidente | None) -> str:
    """Texto del comentario, desde el incidente y la auditoria. Saneado: nada de lo que vino
    del ticket, de los logs o del LLM sale sin pasar por `sanear_linea`."""
    if tipo == "cerrado":
        quien = "sin intervencion humana" if datos.get("autonomo") else "con intervencion humana"
        cabecera = f"RESUELTO {quien}"
    elif tipo == "descartado":
        cabecera = "ESCALADO: la telemetria no confirmo la anomalia del ticket"
    else:
        cabecera = "ESCALADO a L2/SRE"
    lineas = [f"[Agente AIOps] {cabecera}"]
    if inc is not None:
        lineas.append(f"Incidente: {inc.id} · servicio {inc.alerta.servicio}")
        if inc.categoria_id:
            lineas.append(f"Categoria: {inc.categoria_id}")
        if inc.causa:
            lineas.append(f"Diagnostico: {sanear_linea(inc.causa)} (confianza {inc.confianza:.2f})")
        for a in inc.acciones:
            estado = "ok" if a.ok else "fallo"
            lineas.append(f"Accion: {a.nombre} sobre {a.servicio}: {estado}")
        lineas.append(f"Verificado: {'si' if inc.verificado else 'no'}")
    if datos.get("motivo"):
        lineas.append(f"Motivo: {sanear_linea(str(datos['motivo']))}")
    return "\n".join(lineas)


def crear_sink(
    obtener_incidente: Callable[[str], Incidente | None] | None = None,
    entregar: bool = True,
) -> Callable[[Evento], None] | None:
    """Sink para `Auditoria.on_evento`, o None con AIOPS_JIRA=0. Nunca rompe al agente."""
    if not habilitado():
        return None
    if obtener_incidente is None:
        from infra.incidentes_postgres import RepositorioIncidentesPostgres

        obtener_incidente = RepositorioIncidentesPostgres().obtener

    def sink(evento: Evento) -> None:
        destino = _TERMINALES.get(evento.tipo)
        if destino is None or not evento.incidente_id.startswith(_PREFIJO):
            return
        try:
            texto = comentario(evento.tipo, evento.datos, obtener_incidente(evento.incidente_id))
            with psycopg.connect(_url(), autocommit=True) as conn:
                conn.execute(
                    "UPDATE aiops_jira_tickets SET estado = 'pendiente', destino = %s, texto = %s "
                    "WHERE incidente_id = %s AND estado IN ('encolado', 'pendiente')",
                    (destino, texto, evento.incidente_id),
                )
            if entregar:
                cfg = _cargar()
                if cfg is not None:
                    entregar_pendientes(_cliente(cfg), cfg, limite=1)
        except Exception:
            logger.exception("no se pudo dejar el resultado para Jira (el agente sigue)")

    return sink


def entregar_pendientes(cliente: ClienteJira | Any, cfg: ConfigJira, limite: int = 5) -> int:
    """Publica comentario + transicion de los tickets pendientes. Corta en el primer fallo
    de comentario (el siguiente casi seguro falla igual). Devuelve cuantos se comentaron."""
    hechos = 0
    for _ in range(limite):
        with psycopg.connect(_url()) as conn, conn.transaction():
            fila = conn.execute(
                "SELECT clave, destino, texto, intentos FROM aiops_jira_tickets "
                "WHERE estado = 'pendiente' ORDER BY visto_en LIMIT 1 FOR UPDATE SKIP LOCKED"
            ).fetchone()
            if fila is None:
                return hechos
            clave, destino, texto, intentos = fila
            try:
                cliente.comentar(clave, texto)
            except ErrorJira as exc:
                intentos += 1
                conn.execute(
                    "UPDATE aiops_jira_tickets SET intentos = %s, ultimo_error = %s, estado = %s "
                    "WHERE clave = %s",
                    (intentos, str(exc)[:300],
                     "fallido" if intentos >= MAX_INTENTOS else "pendiente", clave),
                )  # fmt: skip
                return hechos
            columna = cfg.resuelto if destino == "resuelto" else cfg.escalado
            error = None
            if columna is not None:
                try:
                    if not cliente.transicionar(clave, columna.estados):
                        error = f"sin transicion a {columna.nombre!r}"
                except ErrorJira as exc:
                    error = str(exc)[:300]
            conn.execute(
                "UPDATE aiops_jira_tickets SET estado = 'comentado', intentos = %s, "
                "ultimo_error = %s WHERE clave = %s",
                (intentos + 1, error, clave),
            )
            hechos += 1
    return hechos
