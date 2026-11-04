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


def _mediana_rango(cs: Sequence[ev.Corrida]) -> str:
    ts = sorted(t for c in cs if (t := c.mttr_s) is not None)
    return f"{median(ts):.1f} s | {ts[0]:.1f}–{ts[-1]:.1f} s" if ts else "– | –"


def _hasta_escalar(cs: Sequence[ev.Corrida]) -> str:
    ts = [t for c in cs if (t := c.escalamiento_s) is not None]
    return f"{median(ts):.1f} s" if ts else "–"


def tabla_resultados(corridas: Sequence[ev.Corrida]) -> str:
    """Tabla 15, separando fallas limpias y variantes confusoras."""
    filas = ["| Resultado | Limpias | Variantes |", "|---|---|---|"]
    limpias = [c for c in corridas if not c.variante]
    variantes = [c for c in corridas if c.variante]
    for r in ev.ResultadoAccion:
        k_l = sum(c.resultado is r for c in limpias)
        k_v = sum(c.resultado is r for c in variantes)
        filas.append(f"| {r.value} | {ev.proporcion(k_l, len(limpias))} | "
                     f"{ev.proporcion(k_v, len(variantes))} |")  # fmt: skip
    return "\n".join(filas)


def tabla_mttr_pareado(corridas: Sequence[ev.Corrida], base: Sequence[ev.CorridaManual]) -> str:
    filas = ["| Escenario | Línea base | Agente | Reducción |", "|---|---|---|---|"]
    for esc, (b, a) in ev.mttr_por_escenario(corridas, base).items():
        filas.append(f"| {esc} | {b:.1f} s | {a:.1f} s | {100 * (b - a) / b:.1f} % |")
    return "\n".join(filas)


def tabla_indicadores(columnas: dict[str, ev.IndicadoresVariantes]) -> str:
    """Los seis indicadores de la tesis (6.6), por condicion."""
    nombres = list(columnas)
    filas = ["| Indicador | " + " | ".join(nombres) + " |", "|---" * (len(nombres) + 1) + "|"]

    def fila(titulo: str, valor: Callable[[ev.IndicadoresVariantes], str]) -> None:
        filas.append(f"| {titulo} | " + " | ".join(valor(columnas[n]) for n in nombres) + " |")

    fila("Abstención previa", lambda i: f"{i.abstencion_previa} de {i.n}")
    fila("Abstención correcta", lambda i: f"{i.abstencion_correcta} de {i.n}")
    fila("Acción ineficaz", lambda i: f"{i.accion_ineficaz} de {i.n}")
    fila("Con reintentos", lambda i: f"{i.con_reintentos} de {i.n}")
    fila(
        "Diagnóstico coincide / parcial",
        lambda i: f"{i.diagnostico_coincide} / {i.diagnostico_parcial} de {i.calificados}",
    )
    fila("Escalamiento completo", lambda i: f"{i.escalamiento_completo} de {i.calificados}")
    fila("Tokens medios", lambda i: f"{i.tokens_medios:.0f}")
    fila("Llamadas a tools medias", lambda i: f"{i.tools_medias:.1f}")
    fila(
        "Tiempo medio por escenario",
        lambda i: "–" if i.tiempo_medio_s is None else f"{i.tiempo_medio_s:.1f} s",
    )
    return "\n".join(filas)


def plantilla_rubrica(filas: Sequence[dict[str, str]], ruta: str) -> int:
    """CSV para calificar a mano: cada incidente escalado o de una variante, con lo que dijo."""
    columnas = [
        "incidente", "escenario", "causa_inyectada", "causa_del_agente", "motivo_escalamiento",
        "diagnostico", "tiene_causa", "tiene_evidencia", "tiene_acciones",
    ]  # fmt: skip
    a_calificar = [
        f for f in filas if f.get("incidente") and (f.get("variante") or f["estado"] == "escalado")
    ]
    with open(ruta, "w", encoding="utf-8", newline="") as salida:
        w = csv.DictWriter(salida, fieldnames=columnas)
        w.writeheader()
        for f in a_calificar:
            variante = f.get("variante") or ""
            w.writerow(
                {
                    "incidente": f["incidente"],
                    "escenario": f["categoria_esperada"] + (f"/{variante}" if variante else ""),
                    "causa_inyectada": variante or f["categoria_esperada"],
                    "causa_del_agente": f.get("causa", ""),
                    "motivo_escalamiento": f.get("motivo_escalamiento", ""),
                }
            )
    return len(a_calificar)


def tabla_por_categoria(corridas: Sequence[ev.Corrida]) -> str:
    filas = [
        "| Escenario | n | Elegible | TRA | MTTR (t2→t5) | Mediana | Rango | Recuperados "
        "| Escalados | Hasta escalar | Precisión clasif. | Acciones incorrectas "
        "| Tokens/inc. | Turnos LLM/inc. |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    grupos: dict[str, list[ev.Corrida]] = {}
    for c in corridas:
        grupos.setdefault(c.escenario, []).append(c)
    for cat, cs in sorted(grupos.items()):
        con_tokens = [c.tokens for c in cs if c.tokens]
        tokens = f"{sum(con_tokens) / len(con_tokens):.0f}" if con_tokens else "–"
        con_turnos = [c.turnos for c in cs if c.turnos]
        turnos = f"{sum(con_turnos) / len(con_turnos):.1f}" if con_turnos else "–"
        filas.append(
            f"| {cat} | {len(cs)} | {'sí' if cs[0].elegible else 'no'} | "
            f"{_fmt(ev.tra, cs, '%')} | {_fmt(ev.mttr, cs, ' s')} | {_mediana_rango(cs)} | "
            f"{sum(c.mttr_s is not None for c in cs)} | "
            f"{sum(c.estado == 'escalado' for c in cs)} | {_hasta_escalar(cs)} | "
            f"{_fmt(ev.precision_clasificacion, cs, '%')} | "
            f"{ev.tasa_acciones_incorrectas(cs):.1f}% | {tokens} | {turnos} |"
        )
    filas.append(
        f"| **Total** | {len(corridas)} | | {_fmt(ev.tra, corridas, '%')} | "
        f"{_fmt(ev.mttr, corridas, ' s')} | {_mediana_rango(corridas)} | "
        f"{sum(c.mttr_s is not None for c in corridas)} | "
        f"{sum(c.estado == 'escalado' for c in corridas)} | {_hasta_escalar(corridas)} | "
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


def _ids(valor: str | None) -> list[str]:
    return [x for x in (valor or "").split("|") if x]


def resumen_rag(filas: Sequence[dict[str, str]]) -> str | None:
    """Brazo con RAG: cuantos diagnosticos citaron una fuente verificada, entre los que
    recuperaron pasajes (si la busqueda no trajo nada no hay nada que citar). Confianza y
    costo se reportan con su n, sin afirmar mejora: con pocas corridas la variabilidad de
    la confianza (0,6 a 0,85 con la misma evidencia) supera cualquier diferencia."""
    con_rag = [f for f in filas if f.get("rag") == "1"]
    if not con_rag:
        return None
    recuperaron = [f for f in con_rag if _ids(f.get("fuentes_recuperadas"))]
    citaron = [f for f in recuperaron if _ids(f.get("fuentes_citadas"))]
    pct = 100 * len(citaron) / len(recuperaron) if recuperaron else 0.0
    tokens = [int(f.get("tokens_entrada") or 0) + int(f.get("tokens_salida") or 0) for f in con_rag]
    confianzas = [float(f["confianza"]) for f in con_rag if f.get("confianza")]
    texto = (
        f"RAG: citas verificadas en {len(citaron)} de {len(recuperaron)} diagnósticos que "
        f"recuperaron pasajes ({pct:.0f} %) · tokens por incidente: mediana {median(tokens):.0f}"
    )
    if confianzas:
        texto += f" · confianza: mediana {median(confianzas):.2f}"
    return texto + f" (n = {len(con_rag)})"


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="Resume un experimento de la Fase 7.")
    p.add_argument("csv")
    p.add_argument("--linea-base", default=None, help="CSV de la linea base manual")
    p.add_argument("--regla", default=None, help="CSV del comparador (--modo reglas)")
    p.add_argument("--calificaciones", default=None, help="rubrica ya calificada")
    p.add_argument(
        "--plantilla-rubrica", default=None, help="escribe el CSV para calificar y termina"
    )
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
    if args.plantilla_rubrica:
        n = plantilla_rubrica(filas, args.plantilla_rubrica)
        print(f"{n} incidentes para calificar en {args.plantilla_rubrica}")
        return 0
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
    rag = resumen_rag(filas)
    if rag:
        print(rag, "\n")
    print("## Resultado de cada acción (Tabla 15)\n")
    print(tabla_resultados(corridas), "\n")
    if base:
        print("## MTTR pareado por escenario (solo casos recuperados)\n")
        print(tabla_mttr_pareado(corridas, base), "\n")
    notas = (
        {c.incidente: c for c in map(ev.Calificacion.desde_fila, _leer(args.calificaciones))}
        if args.calificaciones
        else {}
    )
    columnas = {"Agente": ev.indicadores_variantes(corridas, notas)}
    if args.regla:
        de_regla = filtrar_fase(_leer(args.regla), args.fase)
        columnas["Regla"] = ev.indicadores_variantes(
            [
                ev.Corrida.desde_fila(f)
                for f in de_regla
                if not f.get("error", "").startswith("infra:")
            ],
            notas,
        )
    if any(i.n for i in columnas.values()):
        print("## Variantes confusoras\n")
        print(tabla_indicadores(columnas), "\n")
    print("## Hipótesis\n")
    print(tabla_hipotesis(ev.contrastar(corridas, base)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
