"""Metricas de evaluacion de la tesis: TRA y reduccion de MTTR.

Las cifras objetivo (TRA >= 30%, reduccion >= 20%) son criterios de exito, no
resultados esperados. El denominador de la TRA son solo incidentes L1 elegibles.
"""

from __future__ import annotations

from collections.abc import Sequence

from domain.aiops_core.modelos import AccionEjecutada, Incidente


def tasa_resolucion_autonoma(incidentes: Sequence[Incidente]) -> float:
    """TRA = elegibles resueltos y verificados sin intervencion humana / elegibles * 100."""
    elegibles = [i for i in incidentes if i.elegible]
    if not elegibles:
        raise ValueError("No hay incidentes elegibles: la TRA no esta definida")
    return 100 * sum(i.resuelto_autonomo for i in elegibles) / len(elegibles)


def mttr(incidentes: Sequence[Incidente]) -> float:
    """Segundos promedio desde el disparo de la alerta (`Alerta.disparada_en`, o
    `abierto_en` si el adaptador no lo informa) hasta `cerrado_en`, en incidentes
    resueltos. La tesis exige medir desde el disparo, no desde que el agente abre
    el incidente: un agente lento en recoger la alerta no debe parecer mas rapido."""
    duraciones = [
        i.cerrado_en
        - (i.alerta.disparada_en if i.alerta.disparada_en is not None else i.abierto_en)
        for i in incidentes
        if i.cerrado_en is not None and i.verificado
    ]
    if not duraciones:
        raise ValueError("No hay incidentes resueltos: el MTTR no esta definido")
    return sum(duraciones) / len(duraciones)


def reduccion_mttr(mttr_base: float, mttr_agente: float) -> float:
    """(MTTR base - MTTR agente) / MTTR base * 100. Mismo inicio/fin en ambas mediciones."""
    if mttr_base <= 0:
        raise ValueError("mttr_base debe ser mayor que 0")
    return 100 * (mttr_base - mttr_agente) / mttr_base


def tasa_rollback(incidentes: Sequence[Incidente]) -> float:
    acciones: list[AccionEjecutada] = [a for i in incidentes for a in i.acciones]
    remediaciones = [a for a in acciones if not a.es_rollback]
    if not remediaciones:
        raise ValueError("No hay acciones ejecutadas")
    return 100 * sum(a.es_rollback for a in acciones) / len(remediaciones)
