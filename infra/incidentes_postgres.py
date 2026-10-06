"""Implementacion Postgres del puerto `RepositorioIncidentes` (ver
domain/aiops_core/repositorio.py). Tabla `aiops_incidentes` creada por
migrations/versions/9906268772d6_... (`make migrate`).

Serializa el `Incidente` completo a JSONB en vez de normalizar acciones/alerta en
tablas aparte: evita duplicar el shape de los dataclasses de domain/aiops_core/modelos.py
en un esquema relacional separado. `id`/`estado`/`servicio` quedan ademas en columnas
propias, indexadas, para listar o filtrar sin deserializar cada fila.
"""

from __future__ import annotations

import dataclasses
import os
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from domain.aiops_core.modelos import (
    AccionEjecutada,
    Alerta,
    Aprobacion,
    Estado,
    Incidente,
    Severidad,
)


def _conectar(database_url: str) -> psycopg.Connection[Any]:
    return psycopg.connect(database_url, autocommit=True)


def _a_dict(inc: Incidente) -> dict[str, Any]:
    # dataclasses.asdict recorre Alerta/AccionEjecutada/Aprobacion anidados solo. Los
    # campos Severidad/Estado (StrEnum) quedan como el enum, pero json.dumps los
    # serializa como su valor string porque StrEnum ES un str (sin encoder custom).
    return dataclasses.asdict(inc)


def _desde_dict(d: dict[str, Any]) -> Incidente:
    alerta_d = d["alerta"]
    alerta = Alerta(
        id=alerta_d["id"],
        nombre=alerta_d["nombre"],
        servicio=alerta_d["servicio"],
        entorno=alerta_d["entorno"],
        severidad=Severidad(alerta_d["severidad"]),
        resumen=alerta_d["resumen"],
        disparada_en=alerta_d.get("disparada_en"),
    )
    acciones = [AccionEjecutada(**a) for a in d["acciones"]]
    aprobacion_d = d.get("aprobacion")
    aprobacion = Aprobacion(**aprobacion_d) if aprobacion_d else None
    return Incidente(
        id=d["id"],
        alerta=alerta,
        abierto_en=d["abierto_en"],
        estado=Estado(d["estado"]),
        categoria_id=d.get("categoria_id"),
        anomalia_confirmada=d["anomalia_confirmada"],
        elegible=d["elegible"],
        causa=d.get("causa"),
        confianza=d["confianza"],
        runbook_id=d.get("runbook_id"),
        acciones=acciones,
        verificado=d["verificado"],
        intervencion_humana=d["intervencion_humana"],
        cerrado_en=d.get("cerrado_en"),
        motivo_escalamiento=d.get("motivo_escalamiento"),
        aprobacion=aprobacion,
        # .get con default: las filas guardadas antes de la Fase 6 no tienen estos campos.
        tokens_entrada=d.get("tokens_entrada", 0),
        tokens_salida=d.get("tokens_salida", 0),
    )


class RepositorioIncidentesPostgres:
    """Ver `domain.aiops_core.repositorio.RepositorioIncidentes`. Una conexion nueva
    por operacion: evita manejar pool/concurrencia en esta capa (un pool, si el
    volumen lo justifica, es mejora de la Fase 6 del plan, no de esta)."""

    def __init__(self, database_url: str | None = None) -> None:
        self._url = database_url or os.environ["DATABASE_URL"]

    def guardar(self, incidente: Incidente) -> None:
        with _conectar(self._url) as conn:
            conn.execute(
                "INSERT INTO aiops_incidentes (id, estado, servicio, incidente, actualizado_en) "
                "VALUES (%s, %s, %s, %s, now()) "
                "ON CONFLICT (id) DO UPDATE SET "
                "estado = EXCLUDED.estado, servicio = EXCLUDED.servicio, "
                "incidente = EXCLUDED.incidente, actualizado_en = now()",
                (
                    incidente.id,
                    str(incidente.estado),
                    incidente.alerta.servicio,
                    Jsonb(_a_dict(incidente)),
                ),
            )

    def obtener(self, incidente_id: str) -> Incidente | None:
        with _conectar(self._url) as conn:
            fila = conn.execute(
                "SELECT incidente FROM aiops_incidentes WHERE id = %s", (incidente_id,)
            ).fetchone()
        return _desde_dict(fila[0]) if fila else None

    def listar(self) -> list[Incidente]:
        with _conectar(self._url) as conn:
            filas = conn.execute(
                "SELECT incidente FROM aiops_incidentes ORDER BY actualizado_en"
            ).fetchall()
        return [_desde_dict(f[0]) for f in filas]
