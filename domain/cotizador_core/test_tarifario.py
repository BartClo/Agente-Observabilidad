from datetime import date

import pytest

from domain.cotizador_core.tarifario import tarifa_vigente


def test_tarifa_dentro_de_vigencia() -> None:
    t = tarifa_vigente("NORTE", date(2024, 6, 1))
    assert t.tarifa_base == 12_000.0


def test_tarifa_en_borde_inicial_de_vigencia() -> None:
    t = tarifa_vigente("NORTE", date(2025, 7, 1))
    assert t.tarifa_base == 13_500.0


def test_tarifa_en_borde_final_de_vigencia() -> None:
    t = tarifa_vigente("NORTE", date(2025, 6, 30))
    assert t.tarifa_base == 12_000.0


def test_tarifa_sin_fecha_de_fin_sigue_vigente_a_futuro() -> None:
    t = tarifa_vigente("CENTRO", date(2099, 1, 1))
    assert t.tarifa_base == 8_000.0


def test_sin_tarifa_vigente_lanza_value_error() -> None:
    with pytest.raises(ValueError, match="Sin tarifa vigente"):
        tarifa_vigente("NORTE", date(2020, 1, 1))
