"""Integracion contra el Postgres real del compose (requiere `make migrate` antes:
la tabla aiops_incidentes la crea la migracion, no este test). Igual que
tests/test_infra_observabilidad.py prueba infra/ desde tests/, no desde infra/
(pytest solo recorre tests/domain/agents/rag, ver pyproject.toml)."""

from __future__ import annotations

import os
from collections.abc import Iterator

import psycopg
import pytest

from domain.aiops_core.auditoria import Auditoria
from domain.aiops_core.ciclo import Ciclo
from domain.aiops_core.modelos import Aprobacion, NivelAutonomia
from domain.aiops_core.politicas import Politica
from domain.aiops_core.simulador import EntornoSimulado
from infra.incidentes_postgres import RepositorioIncidentesPostgres, _a_dict


@pytest.fixture
def repo() -> Iterator[RepositorioIncidentesPostgres]:
    yield RepositorioIncidentesPostgres()
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        conn.execute("DELETE FROM aiops_incidentes")


def test_guardar_y_obtener_redondo(repo: RepositorioIncidentesPostgres) -> None:
    assert repo.obtener("INC-no-existe") is None

    env = EntornoSimulado()
    alerta = env.inyectar_fallo("checkout", "servicio_detenido")
    politica = Politica(nivel=NivelAutonomia.AUTONOMO_CON_ROLLBACK)
    ciclo = Ciclo(env, env, politica, Auditoria(), repositorio=repo)
    inc = ciclo.abrir(alerta.id)
    assert inc.id.startswith("INC-")

    leido = repo.obtener(inc.id)
    assert leido is not None
    assert leido.id == inc.id
    assert leido.alerta.servicio == "checkout"
    assert leido.estado == inc.estado

    assert any(i.id == inc.id for i in repo.listar())


def test_sobrevive_acciones_y_aprobacion(repo: RepositorioIncidentesPostgres) -> None:
    """El caso real que motiva la Fase 1: un incidente con acciones ejecutadas y una
    aprobacion registrada tiene que leerse identico tras pasar por Postgres, como si
    el proceso se hubiera reiniciado a mitad del incidente."""
    env = EntornoSimulado()
    alerta = env.inyectar_fallo("billing", "disco_lleno")
    politica = Politica(nivel=NivelAutonomia.CON_APROBACION)
    ciclo = Ciclo(env, env, politica, Auditoria(), repositorio=repo)

    inc_id = ciclo.abrir(alerta.id).id
    ciclo.confirmar_anomalia(inc_id)
    categoria, _, _ = ciclo.clasificar(inc_id)
    assert categoria is not None
    ciclo.registrar_diagnostico(inc_id, "disco lleno de logs", 0.9, categoria.runbook_id)
    ciclo.ejecutar_remediacion(inc_id, aprobada=False)  # queda en REQUIERE APROBACION
    ciclo.aprobar(inc_id, "ana@equipo")
    ciclo.ejecutar_remediacion(inc_id, aprobada=True)

    # "reinicio": un Ciclo nuevo, sobre el mismo repositorio Postgres.
    ciclo2 = Ciclo(env, env, politica, Auditoria(), repositorio=repo)
    recuperado = ciclo2.incidente(inc_id)
    assert len(recuperado.acciones) == 1
    assert recuperado.acciones[0].nombre == "compress_old_logs"
    assert recuperado.aprobacion is not None
    assert recuperado.aprobacion.veredicto == "aprobado"
    assert recuperado.aprobacion.usuario == "ana@equipo"
    assert isinstance(recuperado.aprobacion, Aprobacion)

    ok, _ = ciclo2.verificar(inc_id)
    assert ok
    cerrado = ciclo2.cerrar(inc_id)
    assert cerrado.estado.value == "resuelto"


def test_lee_incidentes_guardados_antes_de_la_fase_6(repo: RepositorioIncidentesPostgres) -> None:
    """Filas viejas no tienen tokens_entrada/tokens_salida en el JSONB: se leen con 0."""
    from psycopg.types.json import Jsonb

    env = EntornoSimulado()
    alerta = env.inyectar_fallo("checkout", "servicio_detenido")
    ciclo = Ciclo(env, env, Politica(), Auditoria(), repositorio=repo)
    inc = ciclo.abrir(alerta.id)
    viejo = {k: v for k, v in _a_dict(inc).items() if not k.startswith("tokens_")}
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        conn.execute(
            "UPDATE aiops_incidentes SET incidente = %s WHERE id = %s", (Jsonb(viejo), inc.id)
        )
    leido = repo.obtener(inc.id)
    assert leido is not None and (leido.tokens_entrada, leido.tokens_salida) == (0, 0)


def test_filas_viejas_sin_ts_en_las_acciones_se_leen_con_none() -> None:
    from domain.aiops_core.modelos import AccionEjecutada, Alerta, Incidente, Severidad
    from infra.incidentes_postgres import _a_dict, _desde_dict

    alerta = Alerta("a1", "ServiceDown", "checkout", "dev", Severidad.ALTA, "r")
    inc = Incidente(id="INC-ts", alerta=alerta, abierto_en=1.0)
    inc.acciones.append(AccionEjecutada("restart_service", "checkout", "ok", True, False, 42.0))
    datos = _a_dict(inc)
    assert _desde_dict(datos).acciones[0].ts == 42.0
    del datos["acciones"][0]["ts"]  # fila guardada antes de existir el campo
    assert _desde_dict(datos).acciones[0].ts is None
