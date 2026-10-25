"""Motor de politicas: decide si una accion se permite, requiere aprobacion o se deniega.

Es codigo determinista: el LLM propone, esta capa dispone. Controles obligatorios de la
tesis cubiertos aca: lista autorizada, acceso por servicio/entorno, umbral de confianza,
limite de reintentos, kill switch y niveles de autonomia.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from domain.aiops_core.acciones import ACCIONES_PERMITIDAS
from domain.aiops_core.catalogo import CategoriaL1
from domain.aiops_core.modelos import Incidente, NivelAutonomia, Severidad


class Veredicto(StrEnum):
    PERMITIR = "permitir"
    APROBACION = "aprobacion"  # permitido, pero un humano debe aprobar antes
    DENEGAR = "denegar"


@dataclass(frozen=True)
class Decision:
    veredicto: Veredicto
    razones: tuple[str, ...]


@dataclass(frozen=True)
class Politica:
    nivel: NivelAutonomia = NivelAutonomia.RECOMIENDA  # arranca en modo recomendacion
    entornos_permitidos: frozenset[str] = frozenset({"dev", "staging"})
    servicios_permitidos: frozenset[str] | None = None  # None = cualquiera del entorno
    umbral_confianza: float = 0.8
    max_reintentos: int = 2
    # Cortacircuito entre incidentes: tope de acciones sobre un mismo servicio dentro de la
    # ventana, sumando TODOS los incidentes (max_reintentos solo mira el actual). 0 = apagado.
    max_acciones_servicio: int = 3
    ventana_cortacircuito_s: float = 3600.0
    kill_switch: Callable[[], bool] = field(default=lambda: False)

    def evaluar(
        self,
        incidente: Incidente,
        categoria: CategoriaL1 | None,
        accion: str,
        *,
        es_rollback: bool = False,
        aprobada: bool = False,
    ) -> Decision:
        """`aprobada=True` solo lo pasa la tool que ya quedo detras de aprobacion humana."""
        if self.kill_switch():
            return _denegar("kill switch activo")
        if accion not in ACCIONES_PERMITIDAS:
            return _denegar(f"accion {accion!r} fuera de la lista autorizada")
        if self.nivel < NivelAutonomia.CON_APROBACION:
            return _denegar(f"autonomia nivel {int(self.nivel)}: solo observa/recomienda")
        if categoria is None or not incidente.elegible:
            return _denegar("incidente no elegible L1")
        if incidente.alerta.severidad is Severidad.CRITICA:
            return _denegar("severidad critica: fuera del alcance autonomo")
        esperada = categoria.rollback if es_rollback else categoria.accion
        if accion != esperada:
            return _denegar(f"{accion!r} no es la accion autorizada para {categoria.id}")
        if incidente.alerta.entorno not in self.entornos_permitidos:
            return _denegar(f"entorno {incidente.alerta.entorno!r} no autorizado")
        if (
            self.servicios_permitidos is not None
            and incidente.alerta.servicio not in self.servicios_permitidos
        ):
            return _denegar(f"servicio {incidente.alerta.servicio!r} no autorizado")
        if incidente.runbook_id != categoria.runbook_id:
            return _denegar("falta diagnostico con el runbook correspondiente")
        if incidente.confianza < self.umbral_confianza:
            return _denegar(
                f"confianza {incidente.confianza:.2f} < umbral {self.umbral_confianza:.2f}"
            )
        if es_rollback:
            if self.nivel < NivelAutonomia.AUTONOMO_CON_ROLLBACK:
                return _denegar("rollback automatico solo en autonomia nivel 4: escalar")
        elif incidente.intentos >= self.max_reintentos:
            return _denegar(f"limite de {self.max_reintentos} reintentos alcanzado")
        if ACCIONES_PERMITIDAS[accion].riesgo != "bajo":
            return Decision(Veredicto.APROBACION, ("accion de riesgo no bajo",))
        if self.nivel is NivelAutonomia.CON_APROBACION and not aprobada:
            return Decision(Veredicto.APROBACION, ("autonomia nivel 2: requiere aprobacion",))
        return Decision(Veredicto.PERMITIR, ("cumple todas las politicas",))


def _denegar(razon: str) -> Decision:
    return Decision(Veredicto.DENEGAR, (razon,))


def politica_desde_entorno(env: Mapping[str, str] | None = None) -> Politica:
    """Lee AIOPS_* del entorno (ver .env.example)."""
    env = os.environ if env is None else env
    servicios = env.get("AIOPS_ALLOWED_SERVICES", "").strip()
    kill_file = env.get("AIOPS_KILL_SWITCH_FILE", "").strip()

    def kill_switch() -> bool:
        return env.get("AIOPS_KILL_SWITCH", "") == "1" or (
            bool(kill_file) and Path(kill_file).exists()
        )

    return Politica(
        nivel=NivelAutonomia(int(env.get("AIOPS_AUTONOMY_LEVEL", "1"))),
        entornos_permitidos=frozenset(
            e.strip() for e in env.get("AIOPS_ALLOWED_ENVS", "dev,staging").split(",") if e.strip()
        ),
        servicios_permitidos=(
            frozenset(s.strip() for s in servicios.split(",") if s.strip()) if servicios else None
        ),
        umbral_confianza=float(env.get("AIOPS_CONFIDENCE_THRESHOLD", "0.8")),
        max_reintentos=int(env.get("AIOPS_MAX_RETRIES", "2")),
        max_acciones_servicio=int(env.get("AIOPS_BREAKER_MAX", "3")),
        ventana_cortacircuito_s=float(env.get("AIOPS_BREAKER_WINDOW_S", "3600")),
        kill_switch=kill_switch,
    )
