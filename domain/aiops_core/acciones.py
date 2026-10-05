"""Lista autorizada de acciones y puerto hacia el backend que las ejecuta.

El ejecutor solo acepta nombres de esta lista y un unico parametro (`servicio`,
validado): el LLM no puede inyectar comandos ni parametros arbitrarios.
"""

from __future__ import annotations

import re
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


def ejecutar_accion(backend: BackendAcciones, accion: str, servicio: str) -> str:
    definicion = ACCIONES_PERMITIDAS.get(accion)
    if definicion is None:
        raise AccionNoPermitida(f"Accion fuera de la lista autorizada: {accion!r}")
    return backend.ejecutar(accion, validar_servicio(servicio), definicion.timeout_s)


class BackendDeshabilitado:
    """Backend por defecto cuando no hay uno real cableado: toda ejecucion falla.
    Deja al agente en modo observar/recomendar/escalar."""

    def ejecutar(self, accion: str, servicio: str, timeout_s: int) -> str:
        raise RuntimeError("No hay backend de acciones configurado: ejecucion deshabilitada.")
