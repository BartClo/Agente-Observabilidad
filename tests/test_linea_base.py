"""La linea base manual se escribe en el formato que lee el analisis (CorridaManual)."""

from __future__ import annotations

import csv
from pathlib import Path

from domain.aiops_core.evaluacion import CorridaManual
from scripts.linea_base import COLUMNAS, escribir_fila


def test_escribe_cabecera_una_vez_y_filas_que_el_analisis_entiende(tmp_path: Path) -> None:
    salida = tmp_path / "r" / "linea_base.csv"
    escribir_fila(salida, "pod_fallido", 421.37, False, "ana", "uso kubectl delete pod")
    escribir_fila(salida, "servicio_detenido", 380.0, True, "ana", "")
    lineas = salida.read_text(encoding="utf-8").splitlines()
    assert lineas[0] == ",".join(COLUMNAS) == "categoria,mttr_s,accion_incorrecta,operador,notas"
    assert len(lineas) == 3
    assert lineas[1].startswith("pod_fallido,421.4,false,ana")

    with salida.open(encoding="utf-8", newline="") as f:
        manuales = [CorridaManual.desde_fila(fila) for fila in csv.DictReader(f)]
    assert [(m.categoria, m.accion_incorrecta) for m in manuales] == [
        ("pod_fallido", False),
        ("servicio_detenido", True),
    ]
