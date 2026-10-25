"""Saneamiento de texto no confiable que llega al LLM (hoy: lineas de log).

Dos objetivos: que un secreto o dato personal en un log no viaje a un proveedor externo
(Tabla 3 de la tesis: "enmascarado de identificadores sensibles") y acotar lo que una
linea puede transportar (un payload hostil repartido en lineas largas).

Es enmascarado por patrones, no una garantia: cubre los casos comunes y se prueba contra
muestras conocidas. Python puro, sin dependencias.
"""

from __future__ import annotations

import re

MAX_LINEA = 300

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_PATRONES: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key|apikey|access[_-]?key)"
            r"""(["']?\s*[:=]\s*["']?)[^\s"',;&]+"""
        ),
        r"\1\2[SECRETO]",
    ),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}"), "Bearer [SECRETO]"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"), "[JWT]"),
    (re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"), "[AWS_KEY]"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"), "[API_KEY]"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[EMAIL]"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "[IP]"),
)


def sanear_linea(linea: str) -> str:
    texto = _CONTROL.sub(" ", linea)
    for patron, reemplazo in _PATRONES:
        texto = patron.sub(reemplazo, texto)
    return texto if len(texto) <= MAX_LINEA else texto[: MAX_LINEA - 1] + "…"
