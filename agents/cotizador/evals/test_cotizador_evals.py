"""Evals de resultado conocido. No invocan el LLM: ejercitan las mismas
funciones que el agente llama (domain + tools), asi que si el LLM elige bien
la tool el resultado es predecible."""

from __future__ import annotations

from datetime import date

import pytest

from agents.cotizador.tools import cotizar_envio
from domain.cotizador_core.cotizador import confirmar, cotizar

CASOS_CONOCIDOS = [
    # origen, destino, peso_kg, fecha, monto_esperado
    ("Bogota", "Barranquilla", 5, date(2024, 3, 1), 12_000 + 2_500 * 5),  # NORTE, tarifa vieja
    ("Bogota", "Barranquilla", 5, date(2025, 8, 1), 13_500 + 2_800 * 5),  # NORTE, tarifa nueva
    ("Bogota", "Medellin", 2, date(2024, 1, 1), 8_000 + 1_800 * 2),  # CENTRO
    ("Bogota", "Cali", 10, date(2024, 6, 1), 15_000 + 3_200 * 10),  # SUR, tarifa vieja
    ("Bogota", "Cali", 10, date(2026, 2, 1), 16_500 + 3_500 * 10),  # SUR, tarifa nueva
]


@pytest.mark.eval
@pytest.mark.parametrize("origen,destino,peso_kg,fecha,monto_esperado", CASOS_CONOCIDOS)
def test_cotizacion_monto_conocido(
    origen: str, destino: str, peso_kg: float, fecha: date, monto_esperado: float
) -> None:
    c = cotizar(origen, destino, peso_kg, fecha)
    assert c.monto_total == monto_esperado


@pytest.mark.eval
def test_confirmar_cotizacion_conocida() -> None:
    c = cotizar("Bogota", "Medellin", peso_kg=3, fecha=date(2024, 1, 1))
    conf = confirmar(c)
    assert conf.estado == "confirmada"
    assert conf.monto_total == 8_000 + 1_800 * 3
    assert len(conf.id) == 12


@pytest.mark.eval
def test_tool_cotizar_envio_formatea_resultado_conocido() -> None:
    resultado = cotizar_envio("Bogota", "Cali", peso_kg=10, fecha="2024-06-01")
    assert "SUR" in resultado
    assert "47,000" in resultado
