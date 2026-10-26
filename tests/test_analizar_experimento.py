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


def _fila(rag: str, rec: str, cit: str, entrada: str = "1000", conf: str = "0.9") -> dict[str, str]:
    return {
        "rag": rag,
        "fuentes_recuperadas": rec,
        "fuentes_citadas": cit,
        "tokens_entrada": entrada,
        "tokens_salida": "200",
        "confianza": conf,
    }


def test_resumen_rag_cuenta_citas_solo_entre_los_que_recuperaron_pasajes() -> None:
    from scripts.analizar_experimento import resumen_rag

    filas = [
        _fila("1", "C1|C2", "C1"),
        _fila("1", "C3", ""),
        _fila("1", "", ""),  # sin pasajes: no cuenta para el porcentaje de citas
    ]
    texto = resumen_rag(filas)
    assert texto is not None
    assert "1 de 2" in texto and "50 %" in texto and "n = 3" in texto


def test_resumen_rag_omite_el_brazo_sin_rag() -> None:
    from scripts.analizar_experimento import resumen_rag

    assert resumen_rag([_fila("0", "", "")]) is None
    assert resumen_rag([{"modo": "llm"}]) is None  # CSV de antes del RAG
