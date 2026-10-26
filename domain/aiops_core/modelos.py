"""Tipos del ciclo de incidentes L1. Sin logica: solo datos."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum, StrEnum


class Severidad(StrEnum):
    BAJA = "baja"
    MEDIA = "media"
    ALTA = "alta"
    CRITICA = "critica"


class NivelAutonomia(IntEnum):
    """Autonomia gradual de la tesis (seccion "Seguridad y autonomia")."""

    OBSERVA = 0  # solo observa y registra
    RECOMIENDA = 1  # recomienda diagnostico y accion
    CON_APROBACION = 2  # ejecuta con aprobacion humana
    AUTONOMO_BAJO_RIESGO = 3  # ejecuta solo acciones L1 de bajo riesgo
    AUTONOMO_CON_ROLLBACK = 4  # ejecuta, verifica y revierte dentro de limites


class Estado(StrEnum):
    ABIERTO = "abierto"
    CONFIRMADO = "confirmado"
    CLASIFICADO = "clasificado"
    DIAGNOSTICADO = "diagnosticado"
    ACCION_EJECUTADA = "accion_ejecutada"
    RESUELTO = "resuelto"
    ESCALADO = "escalado"
    DESCARTADO = "descartado"


@dataclass(frozen=True)
class Alerta:
    id: str
    nombre: str
    servicio: str
    entorno: str
    severidad: Severidad
    resumen: str
    # Instante real del disparo (epoch seconds; `startsAt`/`activeAt` del adaptador).
    # None en el banco simulado. El MTTR de la tesis se mide desde aca, no desde
    # que el agente abre el incidente (ver domain/aiops_core/metricas.py).
    disparada_en: float | None = None


@dataclass(frozen=True)
class AccionEjecutada:
    nombre: str
    servicio: str
    resultado: str
    ok: bool
    es_rollback: bool = False
    # Instante de la accion (reloj del ciclo): lo usa el cortacircuito entre incidentes.
    # None en las filas guardadas antes de este campo.
    ts: float | None = None


@dataclass(frozen=True)
class Aprobacion:
    """Registro en el dominio de una aprobacion humana (nivel 2). No alcanza con que
    el framework pause el grafo (`interrupt_on`): la ejecucion verifica esto aca, no
    confia solo en que alguien haya llamado la tool correcta (ver Ciclo.aprobar)."""

    usuario: str
    ts: float
    veredicto: str  # "aprobado" | "rechazado"


@dataclass
class Incidente:
    id: str
    alerta: Alerta
    abierto_en: float
    estado: Estado = Estado.ABIERTO
    categoria_id: str | None = None
    anomalia_confirmada: bool = False
    elegible: bool = False
    causa: str | None = None
    confianza: float = 0.0
    runbook_id: str | None = None
    acciones: list[AccionEjecutada] = field(default_factory=list)
    verificado: bool = False
    intervencion_humana: bool = False
    cerrado_en: float | None = None
    motivo_escalamiento: str | None = None
    aprobacion: Aprobacion | None = None
    # Costo del LLM al atender el incidente (Fase 6, metrica de la tesis).
    tokens_entrada: int = 0
    tokens_salida: int = 0
    # "proveedor:modelo" que atendio el incidente: comparar corridas exige saberlo.
    modelo_llm: str | None = None
    # Esfuerzo del agente (metrica 6.5 de la tesis): llamadas al LLM y a tools. Las tools
    # incluyen las internas del framework (task, write_todos...), no solo las del ciclo.
    turnos_llm: int = 0
    llamadas_tools: int = 0
    # RAG (informativo): ids de fragmentos que las busquedas devolvieron y los que el
    # diagnostico cito. El dominio rechaza citar lo que no se recupero.
    fuentes_recuperadas: list[str] = field(default_factory=list)
    fuentes_citadas: list[str] = field(default_factory=list)

    @property
    def intentos(self) -> int:
        """Remediaciones intentadas (el rollback no cuenta como reintento)."""
        return sum(1 for a in self.acciones if not a.es_rollback)

    @property
    def resuelto_autonomo(self) -> bool:
        """Resuelto y verificado sin intervencion humana (numerador de la TRA)."""
        return self.estado is Estado.RESUELTO and self.verificado and not self.intervencion_humana
