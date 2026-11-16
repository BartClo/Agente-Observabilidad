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

# "abierto" no avisa: un falso positivo descartado no debe sonar, y lo que importa (que
# actuo, que cerro, que escalo o que pide aprobacion) llega igual en el mismo hilo.
# AIOPS_AVISAR_APERTURA=1 lo vuelve a activar.
HITOS = {"accion", "escalado", "cerrado", "reconciliado"}


def es_hito(evento: Evento) -> bool:
    if evento.tipo == "decision_politica":
        return evento.datos.get("veredicto") == "aprobacion"  # pide a un humano
    if evento.tipo == "abierto":
        return os.environ.get("AIOPS_AVISAR_APERTURA") == "1"
    return evento.tipo in HITOS


def _corto(texto: str, maximo: int) -> str:
    """Primeras oraciones que entran en `maximo`: Chat es un aviso, el detalle va en la UI."""
    texto = limpiar(texto, 10_000)
    if len(texto) <= maximo:
        return texto
    corte = texto.rfind(". ", 0, maximo)
    return texto[: corte + 1] if corte > maximo // 3 else texto[: maximo - 1] + "…"


def formatear(evento: Evento, inc: Incidente | None) -> str:
    """Mensaje de Google Chat (*negrita*, `codigo`), corto y en lineas: titulo, servicio,
    lo esencial y el enlace a la UI. Todo texto de alertas, logs o del LLM pasa por
    `limpiar()`."""
    d = evento.datos
    ui = os.environ.get("AIOPS_UI_URL", "").strip()
    lineas: list[str] = []
    alerta = ""
    if inc is not None:
        a = inc.alerta
        alerta = f" · {limpiar(a.nombre, 80)}"
        lineas.append(f"*Servicio:* `{limpiar(a.servicio, 63)}` ({limpiar(a.entorno, 20)})")
    if evento.tipo == "abierto":
        titulo = "🚨 *Incidente abierto*"
        if inc is not None:
            lineas.append(f"*Severidad:* {limpiar(inc.alerta.severidad, 20)}")
    elif evento.tipo == "accion":
        ok = "✅ ok" if d.get("ok") else "❌ falló"
        titulo = "🔧 *Acción ejecutada*"
        lineas.append(f"*Acción:* `{limpiar(str(d.get('accion', '?')), 60)}` {ok}")
        if d.get("resultado"):
            lineas.append(f"*Resultado:* {_corto(str(d['resultado']), 200)}")
    elif evento.tipo == "escalado":
        titulo = "🔴 *Escalado a L2/SRE*"
        if inc is not None and inc.causa:
            lineas.append(f"*Causa probable:* {_corto(inc.causa, 300)}")
        lineas.append(f"*Motivo:* {_corto(str(d.get('motivo', '')), 350)}")
    elif evento.tipo == "cerrado":
        titulo = "✅ *Resuelto*"
        quien = "sin intervención humana" if d.get("autonomo") else "con intervención humana"
        if inc is not None and inc.cerrado_en is not None:
            inicio = inc.alerta.disparada_en or inc.abierto_en
            quien += f" · {inc.cerrado_en - inicio:.0f} s desde la alerta"
        lineas.append(f"*Cómo:* {quien}")
    elif evento.tipo == "reconciliado":
        titulo = "🛠️ *Reconciliado*"
        lineas.append(
            f"*Estado:* {limpiar(str(d.get('destino', '?')), 20)} · quedó sin cierre "
            f"{float(d.get('edad_s', 0)):.0f} s"
        )
    elif evento.tipo == "decision_politica":  # veredicto "aprobacion"
        titulo = "⏳ *Necesita tu aprobación*"
        razones = "; ".join(str(r) for r in d.get("razones", []))
        lineas.append(f"*Acción:* `{limpiar(str(d.get('accion', '?')), 60)}`")
        lineas.append(f"*Por qué:* {_corto(razones, 300)}")
        lineas.append("Aprobar o rechazar en la UI.")
    else:
        titulo = f"ℹ️ {limpiar(evento.tipo, 40)}"
    if ui and evento.tipo in ("escalado", "decision_politica"):
        lineas.append(f"Detalle completo: {ui}")
    lineas.append(f"_{limpiar(evento.incidente_id, 120)}_")
    return "\n".join([titulo + alerta, *lineas])


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
