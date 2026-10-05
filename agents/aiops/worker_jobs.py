"""Trabajo que corre el worker RQ (profile `redis`, servicio `worker` del compose)
por cada alerta que llega del webhook de Grafana. Separado de `app/api.py`: la API
solo valida, parsea y encola (`POST /webhooks/grafana`), nunca ejecuta esto inline.

Alcance verificado en esta sesion: abrir/auditar el incidente contra el dominio (sin
LLM). Lo que sigue -- que el agente (`build_agent().invoke(...)`) atienda el incidente
de punta a punta -- no se probo en vivo: requiere `ANTHROPIC_API_KEY`, no disponible
en el contenedor de esta sesion. Ver docs/plan-aiops.md Fase 2.
"""

from __future__ import annotations

from typing import Any

from agents.aiops.runtime import get_ciclo
from domain.aiops_core.modelos import Alerta, Severidad


def _alerta_desde_dict(d: dict[str, Any]) -> Alerta:
    return Alerta(
        id=d["id"],
        nombre=d["nombre"],
        servicio=d["servicio"],
        entorno=d["entorno"],
        severidad=Severidad(d["severidad"]),
        resumen=d["resumen"],
        disparada_en=d.get("disparada_en"),
    )


def procesar_alerta_webhook(alerta_dict: dict[str, Any], es_firing: bool) -> str:
    """Punto de entrada del job de RQ. `alerta_dict` es `dataclasses.asdict(alerta)`
    (ver app/api.py), `es_firing` viene de `alerta_desde_grafana()`."""
    alerta = _alerta_desde_dict(alerta_dict)
    ciclo = get_ciclo()
    if not es_firing:
        ciclo.notificar_resuelta_en_origen(alerta)
        return f"{alerta.id}: resuelta en origen, auditada (sin cerrar)"

    inc = ciclo.abrir_desde_alerta(alerta)

    from app.main import build_agent

    pedido = (
        f"Atiende el incidente {inc.id} (alerta {alerta.nombre} en {alerta.servicio}, "
        f"entorno {alerta.entorno}) hasta cerrarlo o escalarlo."
    )
    agent = build_agent()
    agent.invoke({"messages": [{"role": "user", "content": pedido}]})
    return f"{inc.id} procesado por el agente"
