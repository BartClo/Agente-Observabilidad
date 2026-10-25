"""El analisis separa las corridas de ajuste (donde se afina el prompt) de las finales."""

from __future__ import annotations

from scripts.analizar_experimento import filtrar_fase


def test_filtrar_fase_separa_ajuste_de_final() -> None:
    filas = [{"fase": "ajuste", "id": "1"}, {"fase": "final", "id": "2"}, {"id": "3"}]
    assert [f["id"] for f in filtrar_fase(filas, "final")] == ["2"]
    assert [f["id"] for f in filtrar_fase(filas, "ajuste")] == ["1", "3"]  # sin columna = ajuste
    assert len(filtrar_fase(filas, "todas")) == 3


def test_resumen_deteccion_usa_mediana_y_omite_las_filas_sin_dato() -> None:
    from scripts.analizar_experimento import resumen_deteccion

    filas = [{"deteccion_s": "12.0"}, {"deteccion_s": "30.0"}, {"deteccion_s": "20.0"}, {}]
    texto = resumen_deteccion(filas)
    assert texto is not None and "mediana 20.0 s" in texto and "n = 3" in texto
    assert resumen_deteccion([{"deteccion_s": ""}, {}]) is None  # corridas por la via directa
