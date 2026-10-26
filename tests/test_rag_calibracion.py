"""Calibracion del piso de similitud: logica pura, sin red ni base."""

from __future__ import annotations

from datetime import date
from typing import Any

from rag import calibracion
from rag.types import Pasaje


def test_percentil_10_tolera_un_atipico() -> None:
    # con 12 valores el p10 es el segundo: un unico atipico bajo (0.2) no manda
    valores = [0.2, 0.7, 0.72, 0.75, 0.8, 0.8, 0.81, 0.82, 0.83, 0.9, 0.9, 0.95]
    assert calibracion.percentil_10(valores) == 0.7


def test_piso_en_el_punto_medio_si_los_grupos_se_separan() -> None:
    piso, motivo = calibracion.sugerir_piso([0.70, 0.72, 0.75, 0.8], [0.55, 0.58, 0.60])
    assert piso == 0.65 and "separables" in motivo


def test_si_se_solapan_lo_dice_y_sugiere_el_mejor_irrelevante() -> None:
    piso, motivo = calibracion.sugerir_piso([0.60, 0.70, 0.75, 0.8], [0.55, 0.66])
    assert piso == 0.66 and "SE SOLAPAN" in motivo


def test_sin_datos_no_inventa_un_piso() -> None:
    assert calibracion.sugerir_piso([], [0.5])[0] is None


def test_medir_usa_el_mismo_filtro_que_el_agente() -> None:
    visto: list[dict[str, Any]] = []

    def buscar(vector: list[float], **kw: Any) -> list[Pasaje]:
        visto.append(kw)
        return [Pasaje(1, "d.md", None, "x", 0.8 if vector[0] else 0.5, date(2026, 8, 1))]

    consultas = [
        {"q": "relevante", "servicio": "api", "relevante": True},
        {"q": "ajena", "servicio": "api", "relevante": False},
    ]
    rel, irr = calibracion.medir(consultas, lambda q: [1.0 if q == "relevante" else 0.0], buscar)
    assert (rel, irr) == ([0.8], [0.5])
    assert visto[0]["servicio"] == "api" and visto[0]["excluir_tipos"] == ("runbook",)
    assert visto[0]["origenes"] == ("repo",) and visto[0]["k"] == 1
