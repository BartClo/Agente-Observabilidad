"""Calibracion del piso de similitud (AIOPS_RAG_MIN_SIM) con consultas etiquetadas.

El piso evita que un pasaje apenas relacionado haga parecer solido un diagnostico debil.
No se fija a ojo: con Gemini hasta lo irrelevante puntua ~0,55 contra un corpus del mismo
dominio, asi que el valor sale de medir la similitud del MEJOR pasaje de consultas que
deberian encontrar algo (relevantes) y de otras que no (irrelevantes).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from statistics import median
from typing import Any

from rag import store
from rag.embeddings import embed_consulta


def percentil_10(valores: list[float]) -> float:
    ordenados = sorted(valores)
    return ordenados[int(0.1 * (len(ordenados) - 1))]


def sugerir_piso(relevantes: list[float], irrelevantes: list[float]) -> tuple[float | None, str]:
    """Punto medio entre el mejor irrelevante y el p10 de los relevantes. Si se solapan no hay
    piso que separe bien: se dice, y se sugiere el mejor irrelevante (descarta lo claramente
    ajeno aunque deje pasar algo de ruido)."""
    if not relevantes or not irrelevantes:
        return None, "faltan consultas de uno de los dos grupos"
    techo_ruido, piso_senal = max(irrelevantes), percentil_10(relevantes)
    if techo_ruido < piso_senal:
        return round((techo_ruido + piso_senal) / 2, 2), (
            f"separables: el mejor irrelevante ({techo_ruido:.3f}) queda por debajo del p10 "
            f"de los relevantes ({piso_senal:.3f})"
        )
    return round(techo_ruido, 2), (
        f"SE SOLAPAN: el mejor irrelevante ({techo_ruido:.3f}) llega al p10 de los relevantes "
        f"({piso_senal:.3f}); ningun piso separa del todo, no confiar en la similitud sola"
    )


def medir(
    consultas: list[dict[str, Any]],
    embed: Callable[[str], list[float]] = embed_consulta,
    buscar: Callable[..., list[Any]] = store.buscar,
) -> tuple[list[float], list[float]]:
    """Similitud del mejor pasaje de cada consulta, con el mismo filtro que usa el agente."""
    relevantes: list[float] = []
    irrelevantes: list[float] = []
    for c in consultas:
        pasajes = buscar(
            embed(c["q"]),
            servicio=c.get("servicio"),
            k=1,
            min_sim=0.0,
            origenes=("repo",),
            excluir_tipos=("runbook",),
        )
        mejor = pasajes[0].similitud if pasajes else 0.0
        (relevantes if c["relevante"] else irrelevantes).append(mejor)
    return relevantes, irrelevantes


def informe(ruta: Path) -> str:
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    rel, irr = medir(datos["consultas"])
    piso, motivo = sugerir_piso(rel, irr)

    def fila(nombre: str, v: list[float]) -> str:
        return f"{nombre}: n={len(v)} min={min(v):.3f} mediana={median(v):.3f} max={max(v):.3f}"

    return "\n".join(
        [fila("relevantes  ", rel), fila("irrelevantes", irr), motivo, f"piso sugerido: {piso}"]
    )
