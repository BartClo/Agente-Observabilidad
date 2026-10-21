"""Lista autorizada de acciones y puerto hacia el backend que las ejecuta.

El ejecutor solo acepta nombres de esta lista y un unico parametro (`servicio`,
validado): el LLM no puede inyectar comandos ni parametros arbitrarios.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class AccionDef:
    nombre: str
    descripcion: str
    riesgo: str  # "bajo": unico nivel que la autonomia 3 puede ejecutar sola
    timeout_s: int


ACCIONES_PERMITIDAS: dict[str, AccionDef] = {
    a.nombre: a
    for a in (
        AccionDef("restart_service", "Reinicia el servicio.", "bajo", 60),
        AccionDef("compress_old_logs", "Comprime logs rotados antiguos.", "bajo", 120),
        AccionDef("restore_compressed_logs", "Revierte compress_old_logs.", "bajo", 120),
        AccionDef("recreate_pod", "Recrea el pod fallido (lo repone su controlador).", "bajo", 90),
        AccionDef("restart_consumer", "Reinicia el consumidor de la cola.", "bajo", 60),
    )
}

_SERVICIO_VALIDO = re.compile(r"^[A-Za-z0-9_.-]{1,63}$")


class BackendAcciones(Protocol):
    def ejecutar(self, accion: str, servicio: str, timeout_s: int) -> str:
        """Ejecuta la accion y devuelve un resumen. Debe lanzar excepcion si falla."""
        ...


class AccionNoPermitida(ValueError):
    pass


def validar_servicio(servicio: str) -> str:
    if not _SERVICIO_VALIDO.fullmatch(servicio):
        raise AccionNoPermitida(f"Nombre de servicio invalido: {servicio!r}")
    return servicio


class AccionSinRespuesta(TimeoutError):
    """El backend no respondio dentro de `timeout_s` (reloj real). El resultado es
    INCIERTO: la accion pudo haberse aplicado igual. Quien la recibe no debe reintentar
    a ciegas sino verificar y, si no hay recuperacion, escalar."""


def ejecutar_accion(backend: BackendAcciones, accion: str, servicio: str) -> str:
    """Timeout operacional (tesis, RNF de confiabilidad): `timeout_s` es un limite de
    reloj sobre TODA la accion, no por operacion de socket. El timeout de urllib solo
    acota cada lectura: una API lenta que entrega bytes de a poco, o un handshake TLS
    trabado, lo esquivan (corrida del 2026-10-08: 810 s en un rollout restart)."""
    definicion = ACCIONES_PERMITIDAS.get(accion)
    if definicion is None:
        raise AccionNoPermitida(f"Accion fuera de la lista autorizada: {accion!r}")
    servicio = validar_servicio(servicio)
    resultado: list[str] = []
    error: list[BaseException] = []

    def _correr() -> None:
        try:
            resultado.append(backend.ejecutar(accion, servicio, definicion.timeout_s))
        except BaseException as exc:  # se re-lanza en el hilo que espera
            error.append(exc)

    # ponytail: el hilo colgado no se puede matar en Python; queda daemon y muere con el
    # proceso. Un backend que cuelga seguido se arregla en el backend, no aca.
    hilo = threading.Thread(target=_correr, name=f"accion-{accion}", daemon=True)
    hilo.start()
    hilo.join(definicion.timeout_s)
    if hilo.is_alive():
        raise AccionSinRespuesta(
            f"{accion} sin respuesta en {definicion.timeout_s}s: resultado incierto "
            "(pudo aplicarse). Verificar; si no recupera, escalar sin reintentar."
        )
    if error:
        raise error[0]
    return resultado[0]


class BackendDeshabilitado:
    """Backend por defecto cuando no hay uno real cableado: toda ejecucion falla.
    Deja al agente en modo observar/recomendar/escalar."""

    def ejecutar(self, accion: str, servicio: str, timeout_s: int) -> str:
        raise RuntimeError("No hay backend de acciones configurado: ejecucion deshabilitada.")
