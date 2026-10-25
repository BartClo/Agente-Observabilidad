"""Saneamiento de logs antes de que lleguen al LLM (enmascarado y tope por linea)."""

from __future__ import annotations

import pytest

from domain.aiops_core.saneamiento import sanear_linea


@pytest.mark.parametrize(
    ("entrada", "secreto"),
    [
        ("login ok password=hunter2 user=x", "hunter2"),
        ('{"token": "abcdef123456", "ok": true}', "abcdef123456"),
        ("GET /x?api_key=SECRETO123&y=1", "SECRETO123"),
        ("Authorization: Bearer abcdef1234567890", "abcdef1234567890"),
        ("jwt eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTYifQ.SflKxwRJSMeKKF2QT4fw", "eyJhbGci"),
        ("aws AKIAIOSFODNN7EXAMPLE usada", "AKIAIOSFODNN7EXAMPLE"),
        ("clave sk-abcdefghijklmnopqrstuvwx en uso", "sk-abcdefghijklmnopqrstuvwx"),
        ("usuario ana@empresa.cl fallo", "ana@empresa.cl"),
        ("conexion desde 10.1.2.3 rechazada", "10.1.2.3"),
    ],
)
def test_enmascara_lo_sensible(entrada: str, secreto: str) -> None:
    salida = sanear_linea(entrada)
    assert secreto not in salida
    assert "[" in salida  # quedo una marca, no un hueco silencioso


@pytest.mark.parametrize(
    "linea",
    [
        "FATAL checkout: el proceso httpd termino inesperadamente (codigo de salida 143)",
        "INFO checkout: httpd escuchando en :8080 (pid 8)",
        "ERROR api: chequeo de salud fallando (falta /tmp/ok): el pod queda NotReady",
    ],
)
def test_no_toca_las_lineas_de_diagnostico_normales(linea: str) -> None:
    assert sanear_linea(linea) == linea


def test_trunca_y_quita_caracteres_de_control() -> None:
    larga = sanear_linea("x" * 1000)
    assert len(larga) <= 300 and larga.endswith("…")
    assert sanear_linea("a\x00b\x1b[31mc") == "a b [31mc"
