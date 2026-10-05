"""Registro de auditoria append-only: entradas, decisiones, acciones y resultados."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Evento:
    ts: float
    incidente_id: str
    tipo: str
    datos: dict[str, Any]


class Auditoria:
    def __init__(self, ruta: Path | None = None, reloj: Callable[[], float] = time.time) -> None:
        self._ruta = ruta
        self._reloj = reloj
        self.eventos: list[Evento] = []

    def registrar(self, incidente_id: str, tipo: str, **datos: Any) -> None:
        evento = Evento(self._reloj(), incidente_id, tipo, datos)
        self.eventos.append(evento)
        if self._ruta is not None:
            self._ruta.parent.mkdir(parents=True, exist_ok=True)
            linea = json.dumps(
                {"ts": evento.ts, "incidente": incidente_id, "tipo": tipo, "datos": datos},
                ensure_ascii=False,
                default=str,
            )
            with self._ruta.open("a", encoding="utf-8") as f:
                f.write(linea + "\n")

    def de_incidente(self, incidente_id: str) -> list[Evento]:
        return [e for e in self.eventos if e.incidente_id == incidente_id]
