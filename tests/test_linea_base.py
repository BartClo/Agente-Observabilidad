"""La linea base manual se escribe en el formato que lee el analisis (CorridaManual)."""

from __future__ import annotations

import csv
from pathlib import Path

from domain.aiops_core.evaluacion import CorridaManual, ResultadoAccion
from scripts.linea_base import COLUMNAS, escribir_fila


def test_escribe_cabecera_una_vez_y_filas_que_el_analisis_entiende(tmp_path: Path) -> None:
    salida = tmp_path / "r" / "linea_base.csv"
    escribir_fila(salida, "pod_fallido", 421.37, ResultadoAccion.CORRECTA, "ana", "delete pod")
    escribir_fila(
        salida, "pod_fallido/config_invalida", None, ResultadoAccion.DESTINO_INCORRECTO, "ana", ""
    )
    lineas = salida.read_text(encoding="utf-8").splitlines()
    assert lineas[0] == ",".join(COLUMNAS)
    assert len(lineas) == 3

    with salida.open(encoding="utf-8", newline="") as f:
        manuales = [CorridaManual.desde_fila(fila) for fila in csv.DictReader(f)]
    assert [(m.escenario, m.mttr_s, m.accion_incorrecta) for m in manuales] == [
        ("pod_fallido", 421.4, False),
        ("pod_fallido/config_invalida", None, True),  # no resuelto: no se descarta
    ]
