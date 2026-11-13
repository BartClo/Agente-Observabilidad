"""Si el agente falla en el ultimo intento (LLM caido, clave vencida), el incidente se escala
en vez de quedar abierto en silencio. Hallado al levantar el despliegue de AI FACTORY sin LLM."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from agents.aiops import worker_jobs
from domain.aiops_core.modelos import Estado


class CicloFalso:
    def __init__(self, estado: Estado = Estado.ABIERTO) -> None:
        self.estado = estado
        self.escalados: list[str] = []

    def incidente(self, _id: str) -> Any:
        return SimpleNamespace(estado=self.estado)

    def escalar(self, _id: str, motivo: str) -> str:
        self.escalados.append(motivo)
        return motivo


def _job(monkeypatch: pytest.MonkeyPatch, retries_left: int | None) -> None:
    job = None if retries_left is None else SimpleNamespace(retries_left=retries_left)
    monkeypatch.setattr("rq.get_current_job", lambda: job)


def _fallar(ciclo: CicloFalso) -> None:
    worker_jobs._escalar_si_es_el_ultimo_intento(ciclo, "INC-1", TypeError("sin api key"))  # type: ignore[arg-type]


def test_en_el_ultimo_intento_escala_y_dice_por_que(monkeypatch: pytest.MonkeyPatch) -> None:
    _job(monkeypatch, retries_left=0)
    ciclo = CicloFalso()
    _fallar(ciclo)
    assert len(ciclo.escalados) == 1 and "TypeError" in ciclo.escalados[0]


def test_si_quedan_reintentos_no_escala_todavia(monkeypatch: pytest.MonkeyPatch) -> None:
    _job(monkeypatch, retries_left=1)
    ciclo = CicloFalso()
    _fallar(ciclo)
    assert ciclo.escalados == []


def test_fuera_de_rq_se_trata_como_ultimo_intento(monkeypatch: pytest.MonkeyPatch) -> None:
    _job(monkeypatch, retries_left=None)
    ciclo = CicloFalso()
    _fallar(ciclo)
    assert len(ciclo.escalados) == 1


@pytest.mark.parametrize("estado", [Estado.RESUELTO, Estado.ESCALADO, Estado.DESCARTADO])
def test_no_toca_un_incidente_ya_terminado(monkeypatch: pytest.MonkeyPatch, estado: Estado) -> None:
    _job(monkeypatch, retries_left=0)
    ciclo = CicloFalso(estado)
    _fallar(ciclo)
    assert ciclo.escalados == []
