"""agents/aiops/runtime.py arma el Ciclo real del agente segun AIOPS_*. El modo
postgres corre contra la base real del compose (requiere `make migrate`)."""

from __future__ import annotations

import os
from collections.abc import Iterator

import psycopg
import pytest

from agents.aiops import runtime
from domain.aiops_core.repositorio import RepositorioIncidentesMemoria
from infra.incidentes_postgres import RepositorioIncidentesPostgres


@pytest.fixture(autouse=True)
def _reset() -> Iterator[None]:
    runtime.reset()
    yield
    runtime.reset()
    for var in ("AIOPS_PERSISTENCIA", "AIOPS_SIM_FAULTS"):
        os.environ.pop(var, None)
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        conn.execute("DELETE FROM aiops_incidentes")
        conn.execute("DELETE FROM aiops_eventos_auditoria")


def test_persistencia_memoria_es_el_default() -> None:
    ciclo = runtime.get_ciclo()
    assert isinstance(ciclo._repo, RepositorioIncidentesMemoria)


def test_persistencia_postgres_guarda_incidentes_y_auditoria() -> None:
    os.environ["AIOPS_PERSISTENCIA"] = "postgres"
    os.environ["AIOPS_SIM_FAULTS"] = "servicio_detenido:checkout"
    ciclo = runtime.get_ciclo()
    assert isinstance(ciclo._repo, RepositorioIncidentesPostgres)

    alerta_id = ciclo.alertas_activas()[0].split(" | ")[0]
    inc = ciclo.abrir(alerta_id)

    repo_directo = RepositorioIncidentesPostgres()
    assert repo_directo.obtener(inc.id) is not None

    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        fila = conn.execute(
            "SELECT count(*) FROM aiops_eventos_auditoria WHERE incidente_id = %s", (inc.id,)
        ).fetchone()
    assert fila is not None and fila[0] >= 1
