"""Trabajo que corre el worker RQ (profile `redis`, servicio `worker` del compose)
por cada alerta que llega del webhook de Grafana. Separado de `app/api.py`: la API
solo valida, parsea y encola (`POST /webhooks/grafana`), nunca ejecuta esto inline.

Reintentos, timeout y cola de fallidos los configura quien encola (app/api.py): un job
que lanza excepcion se reintenta y, agotados los reintentos, queda en el
FailedJobRegistry de RQ (la cola de mensajes fallidos).

Alcance verificado: abrir/auditar el incidente, el lock por servicio y que las tools
del agente vean el incidente (con un agente falso). Que el LLM real
(`agente.construir().invoke(...)`) atienda el incidente de punta a punta NO se probo: requiere
`ANTHROPIC_API_KEY`. Ver docs/plan-aiops.md.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler

from agents.aiops import runtime
from domain.aiops_core.ciclo import Ciclo
from domain.aiops_core.modelos import Alerta, Estado, Severidad

logger = logging.getLogger(__name__)


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
    reconciliar_colgados(ciclo)
    if not es_firing:
        ciclo.notificar_resuelta_en_origen(alerta)
        return f"{alerta.id}: resuelta en origen, auditada (sin cerrar)"

    with bloqueo_servicio(alerta.servicio):
        inc = ciclo.abrir_desde_alerta(alerta)
        atender_con_agente(ciclo, inc.id, alerta)
    return f"{inc.id} procesado por el agente"


def reconciliar_colgados(ciclo: Ciclo) -> list[str]:
    """Barrido de incidentes que quedaron a medias (agente caido o colgado), al inicio de
    cada job. Best-effort: un fallo aca nunca impide atender la alerta nueva.
    ponytail: solo corre cuando llega una alerta (o POST /reconciliar desde un cron);
    un scheduler propio si hace falta cerrar sin trafico de alertas."""
    try:
        edad = float(os.environ.get("AIOPS_RECONCILIAR_EDAD_S", "1800"))
        return ciclo.reconciliar(edad)
    except Exception:
        logger.exception("reconciliacion de incidentes colgados fallo")
        return []


def pedido_de(incidente_id: str, alerta: Alerta) -> str:
    """Lo primero que lee el agente. El worker ya abrio el incidente (`abrir_desde_alerta`):
    el agente no debe buscar la alerta ni abrirlo de nuevo, sino seguir desde la
    confirmacion. El pedido anterior solo daba el id mientras el prompt arranca por abrir;
    en la primera corrida real del agente unico paro a los 3 turnos."""
    return (
        f"Atiende el incidente {incidente_id} (alerta {alerta.nombre} en {alerta.servicio}, "
        f"entorno {alerta.entorno}) hasta cerrarlo o escalarlo. El incidente YA esta abierto: "
        "no uses listar_alertas_activas ni abrir_incidente; empieza por confirmar_anomalia "
        f"con incidente_id={incidente_id}."
    )


def atender_con_agente(ciclo: Ciclo, incidente_id: str, alerta: Alerta) -> None:
    """El LLM atiende un incidente ya abierto, hasta cerrarlo o escalarlo. Lo usan el
    worker (alertas reales) y scripts/lab_ciclo.py --modo llm (el experimento de la
    Fase 7): mismo pedido, mismas tools, misma medicion de costo."""
    # Las tools del agente (agents/aiops/tools.py) usan runtime.get_ciclo(): tienen que
    # operar sobre ESTE Ciclo (con el incidente abierto) y no sobre un singleton aparte,
    # donde el incidente "no existe". RQ corre cada job en un proceso hijo.
    runtime.reset(ciclo)

    from langchain_core.callbacks import UsageMetadataCallbackHandler

    from agents.aiops.agente import construir, modelo_por_defecto
    from app.main import modelo_de_la_ui, respaldo_de_la_ui

    pedido = pedido_de(incidente_id, alerta)
    # El callback suma el uso de TODAS las llamadas al LLM de la corrida, incluidas las
    # del subagente aiops dentro de su tool call: contar solo los mensajes finales del
    # orquestador subestimaria el costo (Fase 6).
    # Modelo elegido desde la UI (si hay); si no, el de agent.yaml.
    activo = modelo_de_la_ui()
    principal = activo if activo else (None, f"default:{modelo_por_defecto()}")
    respaldo = respaldo_de_la_ui()
    corridas = [principal] + ([respaldo] if respaldo else [])
    uso = UsageMetadataCallbackHandler()
    contador = ContadorTurnos()
    usados: list[str] = []
    primer_error: Exception | None = None
    final: Any = None
    try:
        for i, (modelo, etiqueta) in enumerate(corridas):
            usados.append(etiqueta)
            try:
                final = construir(modelo).invoke(
                    {
                        "messages": [
                            {"role": "user", "content": pedido if i == 0 else _retomar(pedido)}
                        ]
                    },
                    config={"callbacks": [uso, contador]},
                )
                primer_error = None
                break
            except Exception as exc:
                primer_error = primer_error or exc
                # El estado vive en el Ciclo, no en el contexto del LLM: el respaldo puede
                # retomar el incidente donde quedo. Si ya termino, no hay nada que retomar.
                if ciclo.incidente(incidente_id).estado in _TERMINALES or i + 1 >= len(corridas):
                    break
                logger.warning(
                    "%s fallo (%s): se retoma con %s",
                    etiqueta,
                    type(exc).__name__,
                    corridas[i + 1][1],
                )
                ciclo.auditoria.registrar(
                    incidente_id,
                    "llm_respaldo",
                    desde=etiqueta,
                    hacia=corridas[i + 1][1],
                    error=type(exc).__name__,
                )
        if primer_error is not None:
            raise primer_error
        # Fuera del try de las corridas: un fallo aca no debe disparar el respaldo.
        _cerrar_cabos_sueltos(ciclo, incidente_id, final)
    finally:
        # Tambien si el agente fallo a mitad: los tokens gastados igual cuestan.
        entrada, salida = tokens_de(uso.usage_metadata)
        ciclo.registrar_costo_llm(
            incidente_id,
            entrada=entrada,
            salida=salida,
            modelo=" -> ".join(usados),
            turnos=contador.turnos,
            tools=contador.tools,
        )


class ContadorTurnos(BaseCallbackHandler):
    """Cuenta llamadas al LLM (turnos) y a tools de TODA la corrida, incluido el subagente:
    los callbacks de `config` los heredan los runs hijos."""

    def __init__(self) -> None:
        self.turnos = 0
        self.tools = 0

    def on_chat_model_start(self, *args: Any, **kwargs: Any) -> None:
        self.turnos += 1

    def on_tool_start(self, *args: Any, **kwargs: Any) -> None:
        self.tools += 1


_TERMINALES = (Estado.RESUELTO, Estado.ESCALADO, Estado.DESCARTADO)


def _texto_final(resultado: Any) -> str:
    try:
        return str(resultado["messages"][-1].text).strip()
    except (KeyError, IndexError, TypeError, AttributeError):
        return ""


def _cerrar_cabos_sueltos(ciclo: Ciclo, incidente_id: str, resultado: Any) -> None:
    """Un LLM que termina sin cerrar ni escalar deja el incidente en el limbo (corrida
    del 2026-10-21: el agente paro a los 3 turnos). Se deja su ultimo mensaje en la
    auditoria como evidencia y, si el incidente no termino ni espera a un humano
    (nivel 2), se escala: nunca queda abandonado sin que nadie se entere."""
    texto = _texto_final(resultado)
    inc = ciclo.incidente(incidente_id)
    ciclo.auditoria.registrar(incidente_id, "agente_fin", estado=str(inc.estado), texto=texto[:500])
    if inc.estado in _TERMINALES or ciclo.espera_aprobacion(inc):
        return
    ciclo.escalar(
        incidente_id,
        f"El agente termino sin cerrar ni escalar el incidente (estado {inc.estado}). "
        f"Ultimo mensaje del agente: {texto[:400] or '(vacio)'}",
    )


def _retomar(pedido: str) -> str:
    return (
        f"{pedido} Un intento anterior con otro modelo se interrumpio y el incidente puede "
        "estar a medias: consulta `estado_incidente` y continua desde el paso en que quedo, "
        "sin repetir lo que ya se hizo. Si ya se ejecuto una accion, verifica antes de "
        "volver a actuar."
    )


def tokens_de(uso_por_modelo: dict[str, Any]) -> tuple[int, int]:
    """Suma entrada/salida de `UsageMetadataCallbackHandler.usage_metadata` ({modelo:
    {input_tokens, output_tokens, ...}}): el orquestador y el subagente pueden usar
    modelos distintos."""
    entrada = sum(int(u.get("input_tokens", 0)) for u in uso_por_modelo.values())
    salida = sum(int(u.get("output_tokens", 0)) for u in uso_por_modelo.values())
    return entrada, salida
