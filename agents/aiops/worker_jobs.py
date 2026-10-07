"""Trabajo que corre el worker RQ (profile `redis`, servicio `worker` del compose)
por cada alerta que llega del webhook de Grafana. Separado de `app/api.py`: la API
solo valida, parsea y encola (`POST /webhooks/grafana`), nunca ejecuta esto inline.

Reintentos, timeout y cola de fallidos los configura quien encola (app/api.py): un job
que lanza excepcion se reintenta y, agotados los reintentos, queda en el
FailedJobRegistry de RQ (la cola de mensajes fallidos).

Alcance verificado: abrir/auditar el incidente, el lock por servicio y que las tools
del agente vean el incidente (con un agente falso). Que el LLM real
(`build_agent().invoke(...)`) atienda el incidente de punta a punta NO se probo: requiere
`ANTHROPIC_API_KEY`. Ver docs/plan-aiops.md.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from agents.aiops import runtime
from domain.aiops_core.ciclo import Ciclo
from domain.aiops_core.modelos import Alerta, Severidad


class ServicioOcupado(RuntimeError):
    """Otro job ya esta atendiendo un incidente de este servicio. RQ reintenta el job
    mas tarde (ver retry en app/api.py) en vez de remediar dos veces en paralelo."""


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


@contextmanager
def bloqueo_servicio(servicio: str) -> Iterator[None]:
    """Un incidente por servicio a la vez (Fase 6). Lock en Redis con TTL: si el worker
    muere con el lock tomado, se libera solo al vencer (AIOPS_LOCK_TTL_S), en vez de
    bloquear el servicio para siempre."""
    from redis.exceptions import LockNotOwnedError

    from infra.redis_client import get_redis

    lock = get_redis().lock(
        f"aiops:servicio:{servicio}",
        timeout=float(os.environ.get("AIOPS_LOCK_TTL_S", "900")),
        blocking_timeout=float(os.environ.get("AIOPS_LOCK_ESPERA_S", "30")),
    )
    if not lock.acquire():
        raise ServicioOcupado(f"otro incidente de {servicio!r} en curso: se reintenta despues")
    try:
        yield
    finally:
        try:
            lock.release()
        except LockNotOwnedError:
            pass  # vencio el TTL mientras se atendia: ya no es nuestro, nada que liberar


def procesar_alerta_webhook(alerta_dict: dict[str, Any], es_firing: bool) -> str:
    """Punto de entrada del job de RQ. `alerta_dict` es `dataclasses.asdict(alerta)`
    (ver app/api.py), `es_firing` viene de `alerta_desde_grafana()`.

    Arma su propio Ciclo con `persistencia="postgres"` explicito, sin pisar el entorno
    del proceso (ver runtime.armar)."""
    alerta = _alerta_desde_dict(alerta_dict)
    ciclo = runtime.armar(persistencia="postgres")
    if not es_firing:
        ciclo.notificar_resuelta_en_origen(alerta)
        return f"{alerta.id}: resuelta en origen, auditada (sin cerrar)"

    with bloqueo_servicio(alerta.servicio):
        inc = ciclo.abrir_desde_alerta(alerta)
        atender_con_agente(ciclo, inc.id, alerta)
    return f"{inc.id} procesado por el agente"


def atender_con_agente(ciclo: Ciclo, incidente_id: str, alerta: Alerta) -> None:
    """El LLM atiende un incidente ya abierto, hasta cerrarlo o escalarlo. Lo usan el
    worker (alertas reales) y scripts/lab_ciclo.py --modo llm (el experimento de la
    Fase 7): mismo pedido, mismas tools, misma medicion de costo."""
    # Las tools del agente (agents/aiops/tools.py) usan runtime.get_ciclo(): tienen que
    # operar sobre ESTE Ciclo (con el incidente abierto) y no sobre un singleton aparte,
    # donde el incidente "no existe". RQ corre cada job en un proceso hijo.
    runtime.reset(ciclo)

    from langchain_core.callbacks import UsageMetadataCallbackHandler

    from app.main import ORCHESTRATOR_MODEL, build_agent, modelo_de_la_ui

    pedido = (
        f"Atiende el incidente {incidente_id} (alerta {alerta.nombre} en {alerta.servicio}, "
        f"entorno {alerta.entorno}) hasta cerrarlo o escalarlo."
    )
    # El callback suma el uso de TODAS las llamadas al LLM de la corrida, incluidas las
    # del subagente aiops dentro de su tool call: contar solo los mensajes finales del
    # orquestador subestimaria el costo (Fase 6).
    # Modelo elegido desde la UI (si hay); si no, el de agent.yaml / ORCHESTRATOR_MODEL.
    activo = modelo_de_la_ui()
    modelo, etiqueta = activo if activo else (None, f"default:{ORCHESTRATOR_MODEL}")
    uso = UsageMetadataCallbackHandler()
    try:
        build_agent(modelo).invoke(
            {"messages": [{"role": "user", "content": pedido}]},
            config={"callbacks": [uso]},
        )
    finally:
        # Tambien si el agente fallo a mitad: los tokens gastados igual cuestan.
        entrada, salida = tokens_de(uso.usage_metadata)
        ciclo.registrar_costo_llm(incidente_id, entrada=entrada, salida=salida, modelo=etiqueta)


def tokens_de(uso_por_modelo: dict[str, Any]) -> tuple[int, int]:
    """Suma entrada/salida de `UsageMetadataCallbackHandler.usage_metadata` ({modelo:
    {input_tokens, output_tokens, ...}}): el orquestador y el subagente pueden usar
    modelos distintos."""
    entrada = sum(int(u.get("input_tokens", 0)) for u in uso_por_modelo.values())
    salida = sum(int(u.get("output_tokens", 0)) for u in uso_por_modelo.values())
    return entrada, salida
