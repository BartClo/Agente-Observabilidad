"""El worker reconcilia al arrancar: un incidente que quedo huerfano porque el worker murio
no espera a la siguiente alerta (ni al cron de /reconciliar) para cerrarse."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from agents.aiops import arranque, worker_jobs

RAIZ = Path(__file__).resolve().parent.parent


def test_arranque_reconcilia_e_informa(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(arranque, "_ciclo", lambda: object())
    monkeypatch.setattr(worker_jobs, "reconciliar_colgados", lambda c: ["INC-1", "INC-2"])
    assert arranque.main() == 0
    assert "INC-1, INC-2" in capsys.readouterr().out


def test_arranque_nunca_impide_que_el_worker_arranque(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def cae() -> Any:
        raise RuntimeError("postgres todavia no responde")

    monkeypatch.setattr(arranque, "_ciclo", cae)
    assert arranque.main() == 0  # el comando del compose sigue con `;` pase lo que pase
    assert "no se pudo reconciliar" in capsys.readouterr().out


def test_el_compose_reconcilia_antes_de_levantar_el_worker() -> None:
    compose = yaml.safe_load((RAIZ / "docker-compose.yml").read_text(encoding="utf-8"))
    comando = " ".join(compose["services"]["worker"]["command"])
    assert comando.index("agents.aiops.arranque") < comando.index("rq worker")
    assert "--with-scheduler" in comando
    assert "exec" in comando  # rq queda como proceso principal: recibe las senales
