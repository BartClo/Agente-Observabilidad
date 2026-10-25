"""El analisis separa las corridas de ajuste (donde se afina el prompt) de las finales."""

from __future__ import annotations

from scripts.analizar_experimento import filtrar_fase


def test_filtrar_fase_separa_ajuste_de_final() -> None:
    filas = [{"fase": "ajuste", "id": "1"}, {"fase": "final", "id": "2"}, {"id": "3"}]
    assert [f["id"] for f in filtrar_fase(filas, "final")] == ["2"]
    assert [f["id"] for f in filtrar_fase(filas, "ajuste")] == ["1", "3"]  # sin columna = ajuste
    assert len(filtrar_fase(filas, "todas")) == 3
