"""El analisis separa las corridas de ajuste (donde se afina el prompt) de las finales."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from scripts.analizar_experimento import filtrar_fase, main


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


def _corrida(**kw: str) -> dict[str, str]:
    base = {
        "categoria_esperada": "pod_fallido", "categoria_detectada": "pod_fallido",
        "estado": "resuelto", "resuelto_autonomo": "True", "verificado": "True", "acciones": "1",
        "acciones_nombres": "recreate_pod:ok", "t2": "100", "t5": "130", "incidente": "INC-1",
        "fase": "final", "modo": "llm", "variante": "", "motivo_escalamiento": "", "causa": "x",
    }  # fmt: skip
    return {**base, **kw}


def _csv(ruta: Path, filas: list[dict[str, str]]) -> str:
    with ruta.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(filas[0]))
        w.writeheader()
        w.writerows(filas)
    return str(ruta)


def test_informe_completo_con_regla_linea_base_y_rubrica(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    variante = _corrida(
        variante="config_invalida", estado="escalado", resuelto_autonomo="False", acciones="0",
        acciones_nombres="", t5="", incidente="INC-2", causa="ConfigMap",
    )  # fmt: skip
    agente = _csv(tmp_path / "a.csv", [_corrida(), variante])
    regla = _csv(tmp_path / "r.csv", [{**variante, "acciones": "2", "incidente": "INC-3"}])
    base = tmp_path / "b.csv"
    base.write_text(
        "categoria,variante,mttr_s,resultado,accion_incorrecta,operador,notas\n"
        "pod_fallido,,100,correcta,false,ana,\n",
        encoding="utf-8",
    )
    plantilla = tmp_path / "p.csv"
    assert main([agente, "--plantilla-rubrica", str(plantilla)]) == 0
    with plantilla.open(encoding="utf-8", newline="") as f:
        filas = list(csv.DictReader(f))
    assert [(x["incidente"], x["causa_del_agente"]) for x in filas] == [("INC-2", "ConfigMap")]
    filas[0].update(
        diagnostico="coincide", tiene_causa="si", tiene_evidencia="si", tiene_acciones="si"
    )
    notas = _csv(tmp_path / "n.csv", filas)
    capsys.readouterr()

    args = [agente, "--linea-base", str(base), "--regla", regla, "--calificaciones", notas]
    assert main(args) == 0
    salida = capsys.readouterr().out
    assert "pod_fallido/config_invalida" in salida and "| Agente | Regla |" in salida
    assert "| Abstención previa | 1 de 1 | 0 de 1 |" in salida
    assert "| Diagnóstico coincide / parcial | 1 / 0 de 1 | 0 / 0 de 0 |" in salida
    assert "| pod_fallido | 100.0 s | 30.0 s | 70.0 % |" in salida
    assert "H3 variantes" in salida
