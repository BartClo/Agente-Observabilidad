"""Comparador de la tesis (6.1): la automatizacion por reglas, sin modelo de lenguaje. Mismo
ciclo que el agente: confirma, clasifica, registra un diagnostico fijo con confianza 0,9 y
ejecuta siempre la accion del catalogo; si la verificacion falla, reintenta dentro del limite
de la politica y escala."""

from __future__ import annotations

from domain.aiops_core.ciclo import Ciclo

CONFIANZA = 0.9


def atender_con_reglas(ciclo: Ciclo, incidente_id: str) -> None:
    confirmada, detalle = ciclo.confirmar_anomalia(incidente_id)
    if not confirmada:
        ciclo.escalar(incidente_id, f"anomalia no confirmada: {detalle}")
        return
    categoria, elegible, motivos = ciclo.clasificar(incidente_id)
    if not elegible or categoria is None:
        ciclo.escalar(incidente_id, f"no elegible: {motivos}")
        return
    ciclo.registrar_diagnostico(
        incidente_id, f"regla fija: {categoria.nombre}", CONFIANZA, categoria.runbook_id
    )
    while True:
        res = ciclo.ejecutar_remediacion(incidente_id, aprobada=False)
        if not res.ejecutada:  # incluye el limite de reintentos de la politica
            ciclo.escalar(incidente_id, res.mensaje)
            return
        recuperado, _ = ciclo.verificar(incidente_id)
        if recuperado:
            ciclo.cerrar(incidente_id)
            return
