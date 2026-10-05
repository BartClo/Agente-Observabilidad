import pytest

from domain.cotizador_core.zonas import zona_para_destino


def test_zona_conocida() -> None:
    assert zona_para_destino("bogota") == "CENTRO"


def test_zona_case_insensitive_y_trim() -> None:
    assert zona_para_destino("  BogotA ") == "CENTRO"


def test_destino_desconocido_lanza_value_error() -> None:
    with pytest.raises(ValueError, match="sin zona configurada"):
        zona_para_destino("marte")
