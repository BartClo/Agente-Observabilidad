"""Criterio de la evaluacion del chat (sin LLM ni base)."""

from scripts.evaluar_chat import MANUAL, PREGUNTAS, citas, correcta


def test_preguntas_unicas_y_manual_presente() -> None:
    assert len({p.id for p in PREGUNTAS}) == len(PREGUNTAS) == 30
    assert MANUAL.exists()


def test_criterio() -> None:
    d1 = next(p for p in PREGUNTAS if p.id == "d1")
    assert correcta(d1, "Puerto 8443 [C5].", {"C5"})
    assert not correcta(d1, "Puerto 8443.", {"C5"})  # sin cita
    assert not correcta(d1, "Puerto 8443 [C9].", {"C5"})  # cita no recuperada
    assert citas("[C1, C2] y [C3]") == {"C1", "C2", "C3"}
    n4 = next(p for p in PREGUNTAS if p.id == "n4")
    assert not correcta(n4, "No aparece, pero es +56912345678", set())
