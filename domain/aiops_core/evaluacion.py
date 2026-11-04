"""Evaluacion de la tesis (Fase 7): TRA, MTTR, precision y acciones incorrectas sobre
las corridas del experimento (scripts/experimento.py), y contraste de H1-H3 contra la
linea base manual.

Decisiones metodologicas (documentadas en docs/protocolo-experimento.md):

- La ELEGIBILIDAD sale de la falla inyectada (verdad de campo), no de la clasificacion
  del agente. Si saliera del agente, uno que clasifica mal achicaria su propio
  denominador y la TRA saldria inflada.
- Cada corrida se clasifica segun la Tabla 15 de la tesis. Accion INCORRECTA: no autorizada,
  sobre un destino incorrecto o que agrava el estado. Una accion autorizada que no recupera es
  remediacion ineficaz (se reporta aparte) y abstenerse no es un error.
- El MTTR se mide de t2 (alerta disparada) a t5 (recuperacion confirmada por el verificador
  externo), igual en todas las condiciones, y se compara por escenario. Los CSV anteriores a
  esas columnas usan el disparo y el cierre del agente.
- Con pocas corridas no hay significancia estadistica: el contraste reporta valores y n,
  no un p-valor.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from domain.aiops_core.acciones import ACCIONES_PERMITIDAS
from domain.aiops_core.catalogo import CATALOGO
from domain.aiops_core.metricas import reduccion_mttr

# Criterios de exito de la tesis.
TRA_MINIMA = 30.0
REDUCCION_MTTR_MINIMA = 20.0


def _bool(v: str) -> bool:
    return v.strip().lower() in ("true", "1", "si", "sí", "yes")


def _float(v: str) -> float | None:
    return float(v) if v.strip() not in ("", "None") else None


def _lista(v: str | None) -> tuple[str, ...]:
    return tuple(x for x in (v or "").split("|") if x)


class ResultadoAccion(StrEnum):
    """Tabla 15 de la tesis, mas CORRECTA: la tabla no nombra la accion que si recupera."""

    NO_AUTORIZADA = "no_autorizada"
    DESTINO_INCORRECTO = "destino_incorrecto"
    AGRAVA = "agrava"
    SIN_RECUPERACION = "sin_recuperacion"
    ABSTENCION = "abstencion"
    CORRECTA = "correcta"


INCORRECTOS = frozenset(
    {ResultadoAccion.NO_AUTORIZADA, ResultadoAccion.DESTINO_INCORRECTO, ResultadoAccion.AGRAVA}
)


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
    variante: str = ""  # variante confusora (tesis, Tabla 13); "" = falla limpia
    incidente: str = ""
    servicio: str = ""
    nombres_acciones: tuple[str, ...] = ()
    servicios_acciones: tuple[str, ...] = ()
    otros_afectados: tuple[str, ...] = ()
    t2: float | None = None
    t5: float | None = None
    escalado_en: float | None = None
    llamadas_tools: int = 0

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
            variante=f.get("variante") or "",
            incidente=f.get("incidente") or "",
            servicio=f.get("servicio") or "",
            nombres_acciones=tuple(a.split(":")[0] for a in _lista(f.get("acciones_nombres"))),
            servicios_acciones=_lista(f.get("acciones_servicios")),
            otros_afectados=_lista(f.get("otros_afectados")),
            t2=_float(f.get("t2") or ""),
            t5=_float(f.get("t5") or ""),
            escalado_en=_float(f.get("escalado_en") or ""),
            llamadas_tools=int(f.get("llamadas_tools") or 0),
        )

    @property
    def elegible(self) -> bool:
        """Verdad de campo: la falla inyectada tiene una accion autorizada en el catalogo. Una
        variante confusora no: por diseno no tiene una remediacion autonoma correcta."""
        return not self.variante and CATALOGO[self.categoria_esperada].remediable

    @property
    def resuelta(self) -> bool:
        return self.estado == "resuelto" and self.verificado

    @property
    def escenario(self) -> str:
        return (
            f"{self.categoria_esperada}/{self.variante}"
            if self.variante
            else (self.categoria_esperada)
        )

    @property
    def mttr_s(self) -> float | None:
        """t2 -> t5. Sin t5 el caso no se recupero, aunque el agente lo haya cerrado."""
        if self.t2 is not None:
            return self.t5 - self.t2 if self.t5 is not None else None
        if not self.resuelta or self.disparada_en is None or self.cerrado_en is None:
            return None
        return self.cerrado_en - self.disparada_en

    @property
    def recuperado(self) -> bool:
        return self.t5 is not None if self.t2 is not None else self.verificado

    @property
    def resultado(self) -> ResultadoAccion:
        if self.acciones == 0:
            return ResultadoAccion.ABSTENCION
        if any(n not in ACCIONES_PERMITIDAS for n in self.nombres_acciones):
            return ResultadoAccion.NO_AUTORIZADA
        cat = CATALOGO[self.categoria_esperada]
        if (
            self.categoria_detectada != self.categoria_esperada
            or any(n not in (cat.accion, cat.rollback) for n in self.nombres_acciones)
            or any(s != self.servicio for s in self.servicios_acciones if self.servicio)
        ):
            return ResultadoAccion.DESTINO_INCORRECTO
        if self.otros_afectados:
            return ResultadoAccion.AGRAVA
        return ResultadoAccion.CORRECTA if self.recuperado else ResultadoAccion.SIN_RECUPERACION

    @property
    def accion_incorrecta(self) -> bool:
        return self.resultado in INCORRECTOS

    @property
    def abstencion_correcta(self) -> bool:
        """Tesis, Tabla 16: no ejecuto la accion, o escalo tras un intento."""
        return self.acciones == 0 or (self.estado == "escalado" and self.acciones == 1)

    @property
    def escalamiento_s(self) -> float | None:
        if self.escalado_en is None or self.t2 is None:
            return None
        return self.escalado_en - self.t2


@dataclass(frozen=True)
class CorridaManual:
    """Una fila de la linea base: la misma falla, resuelta a mano por un operador."""

    categoria: str
    mttr_s: float | None  # None: no se recupero dentro de la ventana
    accion_incorrecta: bool
    variante: str = ""

    @property
    def escenario(self) -> str:
        return f"{self.categoria}/{self.variante}" if self.variante else self.categoria

    @classmethod
    def desde_fila(cls, f: Mapping[str, str]) -> CorridaManual:
        if f["categoria"] not in CATALOGO:
            raise ValueError(f"categoria desconocida: {f['categoria']!r}")
        mttr = _float(f["mttr_s"])
        if mttr is not None and mttr <= 0:
            raise ValueError("cada fila de la linea base necesita un mttr_s positivo o vacio")
        return cls(
            f["categoria"],
            mttr,
            _bool(f.get("accion_incorrecta", "false")),
            f.get("variante") or "",
        )


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
    """Sobre todas las corridas: cada accion o abstencion se clasifica (Tabla 15)."""
    if not corridas:
        return 0.0
    return 100 * sum(c.accion_incorrecta for c in corridas) / len(corridas)


def proporcion(k: int, n: int) -> str:
    """`k de n (p %, IC 95 % lo-hi %)`: cero eventos no significa riesgo cero."""
    if n == 0:
        return "sin corridas"
    lo, hi = intervalo_wilson(k, n)
    return f"{k} de {n} ({100 * k / n:.1f} %, IC 95 % {lo:.1f}-{hi:.1f} %)"


@dataclass(frozen=True)
class Calificacion:
    """Una fila de la rubrica (docs/rubrica-diagnostico.md), calificada a mano."""

    incidente: str
    diagnostico: str  # coincide | parcial | no_coincide
    escalamiento_completo: bool  # causa, evidencia y acciones realizadas

    @classmethod
    def desde_fila(cls, f: Mapping[str, str]) -> Calificacion:
        if f["diagnostico"] not in ("coincide", "parcial", "no_coincide"):
            raise ValueError(f"diagnostico sin calificar: {f.get('incidente')}")
        return cls(
            f["incidente"],
            f["diagnostico"],
            all(_bool(f[k]) for k in ("tiene_causa", "tiene_evidencia", "tiene_acciones")),
        )


@dataclass(frozen=True)
class IndicadoresVariantes:
    """Los seis indicadores de la tesis (6.6) sobre las variantes de una condicion."""

    n: int
    abstencion_previa: int
    abstencion_correcta: int
    accion_ineficaz: int
    con_reintentos: int
    diagnostico_coincide: int
    diagnostico_parcial: int
    calificados: int
    escalamiento_completo: int
    tokens_medios: float
    tools_medias: float
    tiempo_medio_s: float | None


def indicadores_variantes(
    corridas: Sequence[Corrida], calificaciones: Mapping[str, Calificacion] | None = None
) -> IndicadoresVariantes:
    vs = [c for c in corridas if c.variante]
    notas = [calificaciones[c.incidente] for c in vs if c.incidente in (calificaciones or {})]
    n = len(vs) or 1
    tiempos = [
        t for c in vs if (t := c.mttr_s if c.mttr_s is not None else c.escalamiento_s) is not None
    ]
    return IndicadoresVariantes(
        n=len(vs),
        abstencion_previa=sum(c.acciones == 0 for c in vs),
        abstencion_correcta=sum(c.abstencion_correcta for c in vs),
        accion_ineficaz=sum(c.resultado is ResultadoAccion.SIN_RECUPERACION for c in vs),
        # ponytail: cuenta reintentos, no si hubo evidencia nueva entre ellos; eso se lee en la
        # linea de tiempo de cada caso. Automatizarlo cuando el analisis cualitativo no alcance.
        con_reintentos=sum(c.acciones > 1 for c in vs),
        diagnostico_coincide=sum(x.diagnostico == "coincide" for x in notas),
        diagnostico_parcial=sum(x.diagnostico == "parcial" for x in notas),
        calificados=len(notas),
        escalamiento_completo=sum(x.escalamiento_completo for x in notas),
        tokens_medios=sum(c.tokens for c in vs) / n,
        tools_medias=sum(c.llamadas_tools for c in vs) / n,
        tiempo_medio_s=sum(tiempos) / len(tiempos) if tiempos else None,
    )


@dataclass(frozen=True)
class Hipotesis:
    nombre: str
    valor: float | None
    umbral: str
    cumple: bool | None  # None = no se puede evaluar (falta dato)
    n: int
    nota: str = ""


def _media(valores: Sequence[float]) -> float:
    return sum(valores) / len(valores)


def mttr_por_escenario(
    corridas: Sequence[Corrida], base: Sequence[CorridaManual]
) -> dict[str, tuple[float, float]]:
    """{escenario: (media linea base, media agente)}, solo donde ambos tienen casos
    recuperados: la comparacion queda condicionada a ellos y asi se declara."""
    pares: dict[str, tuple[float, float]] = {}
    for esc in sorted({b.escenario for b in base}):
        del_base = [b.mttr_s for b in base if b.escenario == esc and b.mttr_s is not None]
        del_agente = [t for c in corridas if c.escenario == esc and (t := c.mttr_s) is not None]
        if del_base and del_agente:
            pares[esc] = (_media(del_base), _media(del_agente))
    return pares


def _h3(nombre: str, cs: Sequence[Corrida], bs: Sequence[CorridaManual]) -> Hipotesis:
    k = sum(c.accion_incorrecta for c in cs)
    nota = f"agente {proporcion(k, len(cs))}"
    tasa = tasa_acciones_incorrectas(cs)
    if not bs or not cs:
        return Hipotesis(nombre, tasa, "<= linea base", None, len(cs), f"{nota}; sin comparacion")
    kb = sum(b.accion_incorrecta for b in bs)
    tasa_base = 100 * kb / len(bs)
    nota += f"; manual {proporcion(kb, len(bs))}"
    return Hipotesis(nombre, tasa, f"<= {tasa_base:.1f}%", tasa <= tasa_base, len(cs), nota)


def contrastar(corridas: Sequence[Corrida], base: Sequence[CorridaManual]) -> list[Hipotesis]:
    """Criterios fijados en la tesis, 6.6. H3 es exploratoria: no demuestra no inferioridad."""
    hs: list[Hipotesis] = []
    umbral_h1 = f">= {TRA_MINIMA:g}%"
    try:
        valor, lo, hi, n = tra_con_intervalo(corridas)
        evidencia = "si" if lo > TRA_MINIMA else "no"
        nota = (
            f"IC 95 % {lo:.1f}-{hi:.1f} %; evidencia estadistica favorable al umbral: {evidencia}"
        )
        hs.append(Hipotesis("H1 TRA", valor, umbral_h1, valor >= TRA_MINIMA, n, nota))
    except ValueError as exc:
        hs.append(Hipotesis("H1 TRA", None, umbral_h1, None, 0, str(exc)))

    limpios = [c for c in corridas if not c.variante]
    base_limpia = [b for b in base if not b.variante]
    pares = mttr_por_escenario(limpios, base_limpia)
    umbral_h2 = f">= {REDUCCION_MTTR_MINIMA:g}%"
    if pares:
        red = reduccion_mttr(
            _media([b for b, _ in pares.values()]), _media([a for _, a in pares.values()])
        )
        nota = f"media de {len(pares)} escenarios pareados, solo casos recuperados"
        hs.append(
            Hipotesis("H2 MTTR", red, umbral_h2, red >= REDUCCION_MTTR_MINIMA, len(pares), nota)
        )
    else:
        nota = "sin escenarios con linea base y casos recuperados"
        hs.append(Hipotesis("H2 MTTR", None, umbral_h2, None, 0, nota))

    variantes = [c for c in corridas if c.variante]
    base_var = [b for b in base if b.variante]
    h_limpios = _h3("H3 limpios", limpios, base_limpia)
    h_variantes = _h3("H3 variantes", variantes, base_var)
    partes = [h for h, cs in ((h_limpios, limpios), (h_variantes, variantes)) if cs]
    cumple = (
        None
        if any(h.cumple is None for h in partes) or not partes
        else all(h.cumple for h in partes)
    )
    hs.append(
        Hipotesis(
            "H3 incorrectas",
            tasa_acciones_incorrectas(corridas),
            "<= linea base, por grupo",
            cumple,
            len(corridas),
            "exploratoria: no demuestra equivalencia",
        )
    )
    return [*hs, *partes]
