"""Mapeo ciudad destino -> zona de tarifa.

PLACEHOLDER - validar con experto en logistica. No son zonas reales de ningun
operador; sirven solo para demostrar el patron de "reglas versionadas en
codigo, el LLM no calcula".
"""

from __future__ import annotations

ZONAS: dict[str, str] = {
    "bogota": "CENTRO",
    "medellin": "CENTRO",
    "bucaramanga": "CENTRO",
    "cali": "SUR",
    "pasto": "SUR",
    "barranquilla": "NORTE",
    "cartagena": "NORTE",
}


def zona_para_destino(destino: str) -> str:
    zona = ZONAS.get(destino.strip().lower())
    if zona is None:
        raise ValueError(f"Destino sin zona configurada: {destino!r}")
    return zona
