"""Linea base en QA: toda corrida inyectada queda registrada y el servicio no queda caido."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import pytest

from scripts import linea_base_qa as lb


class Reloj:
    t = 1000.0

    def time(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.t += s

    def strftime(self, _: str) -> str:
        return "x"


@pytest.fixture
def mundo(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Any]:
    reloj = Reloj()
    m: dict[str, Any] = {"caido": False, "t_kill": 0.0, "repara_s": 300.0, "cmds": []}

    def docker(*a: str) -> str:
        m["cmds"].append(a[0])
        if a[0] == "kill":
            m["caido"], m["t_kill"] = True, reloj.t
        if a[0] in ("pause",) or a[:2] == ("network", "disconnect"):
            m["caido"], m["t_kill"] = True, reloj.t
        if a[0] in ("start", "unpause") or a[:2] == ("network", "connect"):
            m["caido"] = False
        if "{{json .NetworkSettings.Networks}}" in a:
            return m.get("redes", '{"red": {"Aliases": ["qa-agent"], "IPAMConfig": null}}')
        m.setdefault("todo", []).append(a)
        return "true" if "{{.State.Running}}" in a else "2026-11-24T12:00:00Z"

    def prom(q: str) -> list[float]:
        pasado = reloj.t - m["t_kill"]
        if "ALERTS" in q:
            return [1.0] if pasado >= 120 else []
        return [0.0] if m["caido"] and pasado < m["repara_s"] else [1.0]

    monkeypatch.setattr(lb, "time", reloj)
    monkeypatch.setattr(lb, "docker", docker)
    monkeypatch.setattr(lb, "prom", prom)
    monkeypatch.setattr(lb, "SALIDA", tmp_path / "b.csv")
    monkeypatch.setattr(lb, "BITACORA", tmp_path / "b.log")
    return m


def _filas() -> list[dict[str, str]]:
    with lb.SALIDA.open(encoding="utf-8", newline="") as h:
        return list(csv.DictReader(h))


def test_resuelta_separa_deteccion_y_atencion(mundo: dict[str, Any]) -> None:
    assert lb.correr(1, "muerto", "qa-agent", "OP1", lambda _: "n") == "resuelta"
    f = _filas()[0]
    assert (f["deteccion_s"], f["atencion_s"], f["mttr_s"]) == ("120", "180", "300")
    assert "start" not in mundo["cmds"]


def test_no_resuelta_se_registra_y_se_levanta(mundo: dict[str, Any]) -> None:
    mundo["repara_s"] = 1e9
    assert lb.correr(1, "muerto", "qa-agent", "OP1", lambda _: "n") == "no_resuelta"
    assert _filas()[0]["mttr_s"] == "" and "start" in mundo["cmds"]


def test_interrumpida_se_registra_y_se_levanta(
    mundo: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def corta(*_: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(lb, "esperar", corta)
    with pytest.raises(KeyboardInterrupt):
        lb.correr(1, "muerto", "qa-agent", "OP1", lambda _: "n")
    assert _filas()[0]["resultado"] == "interrumpida" and "start" in mundo["cmds"]


def test_no_inyecta_si_no_esta_sano(mundo: dict[str, Any]) -> None:
    mundo.update(caido=True, t_kill=1000.0)
    with pytest.raises(SystemExit):
        lb.correr(1, "muerto", "qa-agent", "OP1", lambda _: "n")
    assert "kill" not in mundo["cmds"] and not lb.SALIDA.exists()


@pytest.mark.parametrize(
    ("tipo", "deshacer"),
    [
        ("congelado", ("unpause", "ia-factory-qa-agent")),
        (
            "aislado",
            ("network", "connect", "--alias", "qa-agent", "red", "ia-factory-qa-agent"),
        ),
    ],
)
def test_cada_falla_se_deshace(mundo: dict[str, Any], tipo: str, deshacer: tuple[str]) -> None:
    mundo["repara_s"] = 1e9
    assert lb.correr(1, tipo, "qa-agent", "OP1", lambda _: "n") == "no_resuelta"
    assert deshacer in mundo["todo"] and "kill" not in mundo["cmds"]


def test_transitoria_vuelve_sola_y_no_aporta_mttr(mundo: dict[str, Any]) -> None:
    mundo["repara_s"] = 1e9
    assert lb.correr(1, "transitoria", "qa-agent", "OP1", lambda _: "n") == "volvio_sola"
    assert _filas()[0]["mttr_s"] == ""


def test_no_aisla_con_varias_redes(mundo: dict[str, Any]) -> None:
    mundo["redes"] = '{"a": {}, "b": {}}'
    with pytest.raises(SystemExit):
        lb.correr(1, "aislado", "qa-agent", "OP1", lambda _: "n")
    assert not mundo["caido"]


def test_plan_balancea_tipos(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(lb, "PLAN", tmp_path / "p.json")
    monkeypatch.setattr("sys.argv", ["x", "plan"])
    lb.main()
    orden = lb.json.loads(lb.PLAN.read_text("utf-8"))["orden"]
    assert len(orden) == 16 and all(sum(o[0] == t for o in orden) == 4 for t in lb.TIPOS)
