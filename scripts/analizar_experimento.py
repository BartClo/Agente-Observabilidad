"""Resume un CSV de scripts/experimento.py y contrasta H1-H3 contra la linea base
manual. Imprime tablas Markdown (para pegar en la tesis). Solo stdlib + domain/: corre
dentro o fuera del contenedor.

    python -m scripts.analizar_experimento resultados/llm-nivel3.csv \\
        --linea-base resultados/linea_base.csv
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections.abc import Callable, Sequence
from statistics import median

from domain.aiops_core import evaluacion as ev


def _leer(ruta: str) -> list[dict[str, str]]:
    with open(ruta, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _fmt(
    fn: Callable[[Sequence[ev.Corrida]], float], cs: Sequence[ev.Corrida], sufijo: str = ""
) -> str:
    try:
        return f"{fn(cs):.1f}{sufijo}"
    except ValueError:
        return "–"


def tabla_por_categoria(corridas: Sequence[ev.Corrida]) -> str:
    filas = [
        "| Categoría | n | Elegible | TRA | MTTR | Precisión clasif. "
        "| Acciones incorrectas | Tokens/inc. | Turnos LLM/inc. |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    grupos: dict[str, list[ev.Corrida]] = {}
    for c in corridas:
        grupos.setdefault(c.categoria_esperada, []).append(c)
    for cat, cs in sorted(grupos.items()):
        con_tokens = [c.tokens for c in cs if c.tokens]
        tokens = f"{sum(con_tokens) / len(con_tokens):.0f}" if con_tokens else "–"
        con_turnos = [c.turnos for c in cs if c.turnos]
        turnos = f"{sum(con_turnos) / len(con_turnos):.1f}" if con_turnos else "–"
        filas.append(
            f"| {cat} | {len(cs)} | {'sí' if cs[0].elegible else 'no'} | "
            f"{_fmt(ev.tra, cs, '%')} | {_fmt(ev.mttr, cs, ' s')} | "
            f"{_fmt(ev.precision_clasificacion, cs, '%')} | "
            f"{ev.tasa_acciones_incorrectas(cs):.1f}% | {tokens} | {turnos} |"
        )
    filas.append(
        f"| **Total** | {len(corridas)} | | {_fmt(ev.tra, corridas, '%')} | "
        f"{_fmt(ev.mttr, corridas, ' s')} | "
        f"{_fmt(ev.precision_clasificacion, corridas, '%')} | "
        f"{ev.tasa_acciones_incorrectas(corridas):.1f}% | | |"
    )
    return "\n".join(filas)


def tabla_hipotesis(hs: Sequence[ev.Hipotesis]) -> str:
    filas = ["| Hipótesis | Valor | Criterio | ¿Cumple? | n | Nota |", "|---|---|---|---|---|---|"]
    for h in hs:
        valor = "–" if h.valor is None else f"{h.valor:.1f}%"
        cumple = {True: "sí", False: "**no**", None: "sin datos"}[h.cumple]
        filas.append(f"| {h.nombre} | {valor} | {h.umbral} | {cumple} | {h.n} | {h.nota} |")
    return "\n".join(filas)


def filtrar_fase(filas: Sequence[dict[str, str]], fase: str) -> list[dict[str, str]]:
    """Las corridas de AJUSTE (donde se afina el prompt) no entran en el resultado final:
    medir sobre lo que se uso para afinar infla el resultado. Un CSV sin columna `fase`
    se trata como ajuste."""
    if fase == "todas":
        return list(filas)
    return [f for f in filas if f.get("fase", "ajuste") == fase]


def resumen_deteccion(filas: Sequence[dict[str, str]]) -> str | None:
    """Tiempo de deteccion (anomalia visible -> incidente abierto por el worker). Solo hay
    dato en las corridas por el camino real (`--via webhook`)."""
    valores = sorted(float(f["deteccion_s"]) for f in filas if f.get("deteccion_s"))
    if not valores:
        return None
    return (
        f"Detección (anomalía visible → incidente abierto): mediana {median(valores):.1f} s "
        f"(mín {valores[0]:.1f}, máx {valores[-1]:.1f}, n = {len(valores)})"
    )


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="Resume un experimento de la Fase 7.")
    p.add_argument("csv")
    p.add_argument("--linea-base", default=None, help="CSV de la linea base manual")
    p.add_argument(
        "--fase",
        choices=("final", "ajuste", "todas"),
        default="final",
        help="que corridas analizar; el resultado de la tesis es --fase final",
    )
    args = p.parse_args(argv)
    # La consola de Windows usa cp1252 por defecto y rompe los acentos de las tablas.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    todas = filtrar_fase(_leer(args.csv), args.fase)
    # Las corridas que fallaron por infraestructura (kubectl, Prometheus, inyeccion) no
    # son decisiones del agente: contarlas como "elegible no resuelto" bajaria la TRA
    # injustamente. Se excluyen y se reportan aparte. Los errores del agente SI cuentan.
    infra = [f for f in todas if f.get("error", "").startswith("infra:")]
    filas = [f for f in todas if not f.get("error", "").startswith("infra:")]
    corridas = [ev.Corrida.desde_fila(f) for f in filas]
    base = (
        [ev.CorridaManual.desde_fila(f) for f in _leer(args.linea_base)] if args.linea_base else []
    )
    modos = sorted({f.get("modo", "?") for f in filas})

    print(f"## Resultados: {args.csv}\n")
    print(f"Fase analizada: **{args.fase}**\n")
    print(
        f"Modo: {', '.join(modos)} · corridas válidas: {len(corridas)}"
        f" · excluidas por infraestructura: {len(infra)}\n"
    )
    for f in infra:
        print(
            f"- excluida: corrida {f.get('corrida')} {f.get('categoria_esperada')}:"
            f" {f['error'].splitlines()[0][:120]}"
        )
    if infra:
        print()
    if modos == ["script"]:
        print("> **Atención:** modo `script` (diagnóstico fijo). Prueba la plomería del")
        print("> experimento; NO mide al agente. Correr con `--modo llm` para la tesis.\n")
    print(tabla_por_categoria(corridas), "\n")
    try:
        tra_pct, lo, hi, n_elegibles = ev.tra_con_intervalo(corridas)
        print(
            f"TRA global: **{tra_pct:.1f} %** (IC 95 % de Wilson: {lo:.1f}–{hi:.1f} %, "
            f"n = {n_elegibles} elegibles)\n"
        )
    except ValueError:
        pass
    deteccion = resumen_deteccion(filas)
    if deteccion:
        print(deteccion, "\n")
    print("## Hipótesis\n")
    print(tabla_hipotesis(ev.contrastar(corridas, base)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
