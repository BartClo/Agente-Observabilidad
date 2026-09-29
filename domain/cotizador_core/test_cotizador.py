from datetime import date

import pytest

from domain.cotizador_core.cotizador import Cotizacion, confirmar, cotizar


def test_cotizar_calcula_monto_total() -> None:
    c = cotizar("Bogota", "Cali", peso_kg=10, fecha=date(2024, 6, 1))
    # zona SUR: base 15000 + 3200*10 = 47000
    assert c.zona == "SUR"
    assert c.monto_total == 47_000.0


def test_cotizar_peso_invalido_lanza_value_error() -> None:
    with pytest.raises(ValueError, match="peso_kg"):
        cotizar("Bogota", "Cali", peso_kg=0, fecha=date(2024, 6, 1))


def test_cotizar_destino_desconocido_propaga_error() -> None:
    with pytest.raises(ValueError, match="sin zona configurada"):
        cotizar("Bogota", "Marte", peso_kg=1, fecha=date(2024, 6, 1))


def test_cotizar_sin_tarifa_vigente_propaga_error() -> None:
    with pytest.raises(ValueError, match="Sin tarifa vigente"):
        cotizar("Bogota", "Cali", peso_kg=1, fecha=date(2020, 1, 1))


def test_confirmar_es_deterministico() -> None:
    c = cotizar("Bogota", "Cali", peso_kg=10, fecha=date(2024, 6, 1))
    conf1 = confirmar(c)
    conf2 = confirmar(c)
    assert conf1.id == conf2.id
    assert conf1.estado == "confirmada"
    assert conf1.monto_total == c.monto_total


def test_confirmar_distinta_cotizacion_distinto_id() -> None:
    c1 = cotizar("Bogota", "Cali", peso_kg=10, fecha=date(2024, 6, 1))
    c2 = cotizar("Bogota", "Cali", peso_kg=20, fecha=date(2024, 6, 1))
    assert confirmar(c1).id != confirmar(c2).id


def test_cotizacion_es_inmutable() -> None:
    c = cotizar("Bogota", "Cali", peso_kg=10, fecha=date(2024, 6, 1))
    with pytest.raises(AttributeError):
        c.monto_total = 0  # type: ignore[misc]


def test_cotizacion_dataclass_tiene_los_campos_esperados() -> None:
    c = cotizar("Bogota", "Cali", peso_kg=10, fecha=date(2024, 6, 1))
    assert isinstance(c, Cotizacion)
    assert c.origen == "Bogota"
    assert c.destino == "Cali"
