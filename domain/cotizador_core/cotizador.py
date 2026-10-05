"""Calculo de cotizacion y confirmacion. El LLM nunca hace esta cuenta, solo
llama las tools que envuelven estas funciones (ver agents/cotizador/tools.py)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date

from domain.cotizador_core.tarifario import tarifa_vigente
from domain.cotizador_core.zonas import zona_para_destino


@dataclass(frozen=True)
class Cotizacion:
    origen: str
    destino: str
    zona: str
    peso_kg: float
    fecha: date
    tarifa_base: float
    costo_por_kg: float
    monto_total: float


@dataclass(frozen=True)
class Confirmacion:
    id: str
    monto_total: float
    estado: str


def cotizar(origen: str, destino: str, peso_kg: float, fecha: date) -> Cotizacion:
    if peso_kg <= 0:
        raise ValueError("peso_kg debe ser mayor que 0")
    zona = zona_para_destino(destino)
    tarifa = tarifa_vigente(zona, fecha)
    monto_total = tarifa.tarifa_base + tarifa.costo_por_kg * peso_kg
    return Cotizacion(
        origen=origen,
        destino=destino,
        zona=zona,
        peso_kg=peso_kg,
        fecha=fecha,
        tarifa_base=tarifa.tarifa_base,
        costo_por_kg=tarifa.costo_por_kg,
        monto_total=monto_total,
    )


def confirmar(cotizacion: Cotizacion) -> Confirmacion:
    """Efecto simulado: en un sistema real esto crearia una orden. Aca solo arma
    un id deterministico; la tool que la envuelve (`confirmar_cotizacion`) es la
    que queda detras de aprobacion humana (regla 6)."""
    raw = (
        f"{cotizacion.origen}|{cotizacion.destino}|{cotizacion.peso_kg}|"
        f"{cotizacion.fecha.isoformat()}|{cotizacion.monto_total}"
    )
    confirmacion_id = hashlib.sha256(raw.encode()).hexdigest()[:12]
    return Confirmacion(id=confirmacion_id, monto_total=cotizacion.monto_total, estado="confirmada")
