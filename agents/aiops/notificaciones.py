"""Avisos del agente a Google Chat: lo que va haciendo, sin pasar por el LLM.

Sale de la auditoria (el sink se engancha a `Auditoria.on_evento`, ver runtime.armar),
asi que el aviso es exacto, no gasta tokens y refleja lo que de verdad paso. Solo se
avisa de los hitos de un incidente; el detalle fino queda en la linea de tiempo de la UI.

Nunca rompe al agente: cualquier fallo aca (Postgres, Google Chat, formato) se registra
y se ignora. La entrega es por bandeja de salida (infra/notificaciones.py).
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from typing import Any

from domain.aiops_core.auditoria import Evento
from domain.aiops_core.modelos import Incidente
from infra.gchat import limpiar

logger = logging.getLogger(__name__)

HITOS = {"abierto", "accion", "escalado", "cerrado", "reconciliado"}


def es_hito(evento: Evento) -> bool:
    if evento.tipo == "decision_politica":
        return evento.datos.get("veredicto") == "aprobacion"  # pide a un humano
    return evento.tipo in HITOS


def formatear(evento: Evento, inc: Incidente | None) -> str:
    """Mensaje de Google Chat (*negrita*, `codigo`). Todo texto que viene de alertas,
    logs o del LLM pasa por `limpiar()`."""
    d = evento.datos
    ui = os.environ.get("AIOPS_UI_URL", "").strip()
    pie = f"\n{ui}" if ui else ""
    ident = f"`{limpiar(evento.incidente_id, 120)}`"
    donde = ""
    if inc is not None:
        a = inc.alerta
        donde = f"{limpiar(a.nombre, 80)} en `{limpiar(a.servicio, 63)}` ({limpiar(a.entorno, 20)})"
    if evento.tipo == "abierto":
        sev = f" · severidad {inc.alerta.severidad}" if inc else ""
        return f"🚨 *Incidente abierto* {ident}\n{donde}{sev}"
    if evento.tipo == "accion":
        ok = "✅ ok" if d.get("ok") else "❌ falló"
        accion = limpiar(str(d.get("accion", "?")), 60)
        detalle = limpiar(str(d.get("resultado", "")), 300)
        return f"🔧 *Acción ejecutada* {ident}: `{accion}` {ok}\n{detalle}"
    if evento.tipo == "escalado":
        return (
            f"🔴 *Escalado a L2/SRE* {ident}\n{donde}\n"
            f"Motivo: {limpiar(str(d.get('motivo', '')), 1200)}{pie}"
        )
    if evento.tipo == "cerrado":
        quien = "sin intervención humana" if d.get("autonomo") else "con intervención humana"
        tiempo = ""
        if inc is not None and inc.cerrado_en is not None:
            inicio = inc.alerta.disparada_en or inc.abierto_en
            tiempo = f" · {inc.cerrado_en - inicio:.0f} s desde la alerta"
        return f"✅ *Resuelto* {ident} {quien}{tiempo}\n{donde}"
    if evento.tipo == "reconciliado":
        return (
            f"🛠️ *Reconciliado* {ident} → {limpiar(str(d.get('destino', '?')), 20)}: "
            f"quedó sin cierre {float(d.get('edad_s', 0)):.0f} s\n{donde}"
        )
    if evento.tipo == "decision_politica":  # veredicto "aprobacion"
        razones = limpiar("; ".join(str(r) for r in d.get("razones", [])), 300)
        return (
            f"⏳ *Necesita tu aprobación* {ident}\n{donde}\n"
            f"Acción `{limpiar(str(d.get('accion', '?')), 60)}`: {razones}\n"
            f"Aprobar o rechazar en la UI.{pie}"
        )
    return f"ℹ️ {limpiar(evento.tipo, 40)} {ident}"


def crear_sink(
    webhook_url: str | None = None,
    obtener_incidente: Callable[[str], Incidente | None] | None = None,
) -> Callable[[Evento], None] | None:
    """Sink para `Auditoria.on_evento`, o None si no hay webhook configurado
    (AIOPS_GCHAT_WEBHOOK_URL): sin URL el agente funciona igual, sin avisos."""
    url = webhook_url if webhook_url is not None else os.environ.get("AIOPS_GCHAT_WEBHOOK_URL", "")
    url = url.strip()
    if not url:
        return None
    from infra import notificaciones
    from infra.gchat import validar_url

    validar_url(url)  # falla al armar, no en el primer incidente

    if obtener_incidente is None:
        from infra.incidentes_postgres import RepositorioIncidentesPostgres

        obtener_incidente = RepositorioIncidentesPostgres().obtener

    def sink(evento: Evento) -> None:
        if not es_hito(evento):
            return
        try:
            texto = formatear(evento, obtener_incidente(evento.incidente_id))
            clave = f"{evento.incidente_id}:{evento.tipo}:{evento.ts:.6f}"
            notificaciones.encolar(clave, evento.incidente_id, evento.tipo, texto)
            notificaciones.entregar_pendientes(url, limite=5)
        except Exception:
            logger.exception("no se pudo avisar a Google Chat (el agente sigue)")

    return sink


def componer(*sinks: Callable[[Evento], None] | None) -> Callable[[Evento], None] | None:
    """Une sinks de auditoria en orden. El primero (Postgres) puede fallar y propagar;
    los siguientes ya corren protegidos."""
    activos = [s for s in sinks if s is not None]
    if not activos:
        return None

    def todos(evento: Evento) -> None:
        for s in activos:
            s(evento)

    return todos


def estado() -> dict[str, Any]:
    from infra import notificaciones

    return {
        "configurado": bool(os.environ.get("AIOPS_GCHAT_WEBHOOK_URL", "").strip()),
        **notificaciones.conteos(),
    }
