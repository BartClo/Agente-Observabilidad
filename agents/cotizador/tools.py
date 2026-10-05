"""Tools del agente `cotizador`. Solo formatean input/output; el calculo real
vive en domain/cotizador_core (el LLM no calcula nada, regla 2)."""

from __future__ import annotations

from datetime import date

from domain.cotizador_core import cotizador


def cotizar_envio(origen: str, destino: str, peso_kg: float, fecha: str) -> str:
    """Cotiza un envio. `fecha` en formato YYYY-MM-DD. No tiene efectos: solo lectura."""
    c = cotizador.cotizar(origen, destino, peso_kg, date.fromisoformat(fecha))
    return (
        f"Cotizacion {c.origen} -> {c.destino} (zona {c.zona}): "
        f"${c.monto_total:,.0f} (base ${c.tarifa_base:,.0f} + "
        f"${c.costo_por_kg:,.0f}/kg x {c.peso_kg}kg)"
    )


def confirmar_cotizacion(origen: str, destino: str, peso_kg: float, fecha: str) -> str:
    """Confirma un envio: efecto real (crea la orden). Requiere aprobacion humana."""
    c = cotizador.cotizar(origen, destino, peso_kg, date.fromisoformat(fecha))
    confirmacion = cotizador.confirmar(c)
    return (
        f"Confirmado. id={confirmacion.id} "
        f"monto=${confirmacion.monto_total:,.0f} estado={confirmacion.estado}"
    )
