"""Evaluacion de la tesis (Fase 7): TRA, MTTR, precision y acciones incorrectas sobre
las corridas del experimento (scripts/experimento.py), y contraste de H1-H3 contra la
linea base manual.

Decisiones metodologicas (documentadas en docs/protocolo-experimento.md):

- La ELEGIBILIDAD sale de la falla inyectada (verdad de campo), no de la clasificacion
  del agente. Si saliera del agente, uno que clasifica mal achicaria su propio
  denominador y la TRA saldria inflada.
- Accion INCORRECTA: el agente ejecuto al menos una accion y, o bien clasifico otra
  categoria que la inyectada, o bien el servicio no quedo verificado como recuperado.
- El MTTR se mide del disparo de la alerta al cierre verificado, en el agente y en la
  linea base (mismo inicio y fin), por categoria.
- Con pocas corridas no hay significancia estadistica: el contraste reporta valores y n,
  no un p-valor.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from domain.aiops_core.catalogo import CATALOGO
from domain.aiops_core.metricas import reduccion_mttr

# Criterios de exito de la tesis.
TRA_MINIMA = 30.0
REDUCCION_MTTR_MINIMA = 20.0


def _bool(v: str) -> bool:
    return v.strip().lower() in ("true", "1", "si", "sí", "yes")


def _float(v: str) -> float | None:
    return float(v) if v.strip() not in ("", "None") else None


@dataclass(frozen=True)
class Corrida:
    """Una fila del CSV del experimento: una falla inyectada atendida por el agente."""

    categoria_esperada: str
    categoria_detectada: str | None
    estado: str
    resuelto_autonomo: bool
    verificado: bool
    acciones: int
    disparada_en: float | None
    cerrado_en: float | None
    tokens: int = 0
    turnos: int = 0

    @classmethod
    def desde_fila(cls, f: Mapping[str, str]) -> Corrida:
        if f["categoria_esperada"] not in CATALOGO:
            raise ValueError(f"categoria_esperada desconocida: {f['categoria_esperada']!r}")
        return cls(
            categoria_esperada=f["categoria_esperada"],
            categoria_detectada=f.get("categoria_detectada") or None,
            estado=f["estado"],
            resuelto_autonomo=_bool(f["resuelto_autonomo"]),
            verificado=_bool(f["verificado"]),
            acciones=int(f.get("acciones") or 0),
            disparada_en=_float(f.get("disparada_en", "")),
            cerrado_en=_float(f.get("cerrado_en", "")),
            tokens=int(f.get("tokens_entrada") or 0) + int(f.get("tokens_salida") or 0),
            turnos=int(f.get("turnos_llm") or 0),
        )

    @property
    def elegible(self) -> bool:
        """Verdad de campo: la falla inyectada tiene una accion autorizada en el catalogo."""
        return CATALOGO[self.categoria_esperada].remediable

    @property
    def resuelta(self) -> bool:
        return self.estado == "resuelto" and self.verificado

    @property
    def mttr_s(self) -> float | None:
        if not self.resuelta or self.disparada_en is None or self.cerrado_en is None:
            return None
        return self.cerrado_en - self.disparada_en

    @property
    def accion_incorrecta(self) -> bool:
        if self.acciones == 0:
            return False
        return self.categoria_detectada != self.categoria_esperada or not self.verificado


@dataclass(frozen=True)
class CorridaManual:
    """Una fila de la linea base: la misma falla, resuelta a mano por un operador."""

    categoria: str
    mttr_s: float
    accion_incorrecta: bool

    @classmethod
    def desde_fila(cls, f: Mapping[str, str]) -> CorridaManual:
        if f["categoria"] not in CATALOGO:
            raise ValueError(f"categoria desconocida: {f['categoria']!r}")
        mttr = _float(f["mttr_s"])
        if mttr is None or mttr <= 0:
            raise ValueError("cada fila de la linea base necesita un mttr_s positivo")
        return cls(f["categoria"], mttr, _bool(f.get("accion_incorrecta", "false")))


def tra(corridas: Sequence[Corrida]) -> float:
    elegibles = [c for c in corridas if c.elegible]
    if not elegibles:
        raise ValueError("No hay corridas elegibles: la TRA no esta definida")
    return 100 * sum(c.resuelto_autonomo for c in elegibles) / len(elegibles)


def intervalo_wilson(exitos: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Intervalo de confianza de Wilson (95 % por defecto) para una proporcion, en %.
    Con n chico un porcentaje sin su intervalo engana: 3 de 5 es 60 % pero el intervalo va
    de 23 % a 88 %."""
    if n <= 0 or not 0 <= exitos <= n:
        raise ValueError("n debe ser positivo y 0 <= exitos <= n")
    p = exitos / n
    denom = 1 + z * z / n
    centro = (p + z * z / (2 * n)) / denom
    margen = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, 100 * (centro - margen)), min(100.0, 100 * (centro + margen))


def tra_con_intervalo(corridas: Sequence[Corrida]) -> tuple[float, float, float, int]:
    """(TRA %, limite inferior %, limite superior %, n de elegibles)."""
    elegibles = [c for c in corridas if c.elegible]
    if not elegibles:
        raise ValueError("No hay corridas elegibles: la TRA no esta definida")
    k = sum(c.resuelto_autonomo for c in elegibles)
    lo, hi = intervalo_wilson(k, len(elegibles))
    return 100 * k / len(elegibles), lo, hi, len(elegibles)


def mttr(corridas: Iterable[Corrida]) -> float:
    tiempos = [t for c in corridas if (t := c.mttr_s) is not None]
    if not tiempos:
        raise ValueError("Ninguna corrida quedo resuelta y verificada")
    return sum(tiempos) / len(tiempos)


def precision_clasificacion(corridas: Sequence[Corrida]) -> float:
    if not corridas:
        raise ValueError("Sin corridas")
    return (
        100 * sum(c.categoria_detectada == c.categoria_esperada for c in corridas) / len(corridas)
    )


def tasa_acciones_incorrectas(corridas: Sequence[Corrida]) -> float:
    """Sobre las corridas en las que se actuo: actuar mal, no abstenerse, es lo que mide H3."""
    con_accion = [c for c in corridas if c.acciones > 0]
    if not con_accion:
        return 0.0
    return 100 * sum(c.accion_incorrecta for c in con_accion) / len(con_accion)


@dataclass(frozen=True)
class Hipotesis:
    nombre: str
    valor: float | None
    umbral: str
    cumple: bool | None  # None = no se puede evaluar (falta dato)
    n: int
    nota: str = ""


def contrastar(corridas: Sequence[Corrida], base: Sequence[CorridaManual]) -> list[Hipotesis]:
    """H1: TRA >= 30%. H2: reduccion de MTTR >= 20% (en las categorias que el agente
    resolvio y que tienen linea base). H3: sin aumento de acciones incorrectas."""
    hs: list[Hipotesis] = []

    elegibles = sum(c.elegible for c in corridas)
    try:
        valor_tra = tra(corridas)
        hs.append(
            Hipotesis(
                "H1 TRA", valor_tra, f">= {TRA_MINIMA:g}%", valor_tra >= TRA_MINIMA, elegibles
            )
        )
    except ValueError as exc:
        hs.append(Hipotesis("H1 TRA", None, f">= {TRA_MINIMA:g}%", None, 0, str(exc)))

    reducciones: list[float] = []
    for cat in sorted({b.categoria for b in base}):
        del_agente = [c for c in corridas if c.categoria_esperada == cat]
        if not any(c.mttr_s is not None for c in del_agente):
            continue
        base_cat = [b.mttr_s for b in base if b.categoria == cat]
        reducciones.append(reduccion_mttr(sum(base_cat) / len(base_cat), mttr(del_agente)))
    if reducciones:
        red = sum(reducciones) / len(reducciones)
        umbral = f">= {REDUCCION_MTTR_MINIMA:g}%"
        nota = f"promedio de {len(reducciones)} categorias"
        hs.append(
            Hipotesis("H2 MTTR", red, umbral, red >= REDUCCION_MTTR_MINIMA, len(reducciones), nota)
        )
    else:
        nota = "sin categorias con linea base y corridas resueltas"
        hs.append(Hipotesis("H2 MTTR", None, f">= {REDUCCION_MTTR_MINIMA:g}%", None, 0, nota))

    tasa_agente = tasa_acciones_incorrectas(corridas)
    if base:
        tasa_base = 100 * sum(b.accion_incorrecta for b in base) / len(base)
        nota = f"agente {tasa_agente:.1f}% vs manual {tasa_base:.1f}%"
        hs.append(
            Hipotesis(
                "H3 incorrectas",
                tasa_agente,
                f"<= {tasa_base:.1f}%",
                tasa_agente <= tasa_base,
                len(corridas),
                nota,
            )
        )
    else:
        hs.append(
            Hipotesis(
                "H3 incorrectas",
                tasa_agente,
                "<= linea base",
                None,
                len(corridas),
                "sin linea base manual",
            )
        )
    return hs
