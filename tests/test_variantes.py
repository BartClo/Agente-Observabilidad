"""Variantes confusoras: plan, tope y envio de logs (sin Docker)."""

import calendar

from scripts import variantes as v


def test_plan_equilibrado_y_reproducible() -> None:
    plan = v.plan(3)
    assert plan == v.plan(3)
    assert len(plan) == len(set(plan)) == 3 * 2 * len(v.VARIANTES)
    por_bloque = 2 * len(v.VARIANTES)
    for n in range(3):
        assert {p[0] for p in plan[n * por_bloque : (n + 1) * por_bloque]} == {n + 1}


def test_cota() -> None:
    assert v.cota_usd(1_000_000, 100_000) == 5.0


def test_lineas_loki_convierte_utc_y_descarta_basura() -> None:
    esperado = calendar.timegm((2026, 11, 25, 9, 30, 1))
    assert v.lineas_loki("2026-11-25T09:30:01.5Z FATAL algo malo\nbasura") == [
        [f"{esperado}500000000", "FATAL algo malo"]
    ]


def test_cada_variante_usa_scripts_que_existen() -> None:
    for e in v.VARIANTES.values():
        assert (v.ex.RAIZ / "scripts" / "fallas" / e.falla).exists()
        assert e.recuperar and (v.ex.RAIZ / "scripts" / "fallas" / e.recuperar).exists()
