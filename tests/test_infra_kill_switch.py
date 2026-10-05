"""Integracion contra el Postgres real del compose (requiere `make migrate`, que deja
la fila unica de aiops_kill_switch en activo=false)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from infra import kill_switch


@pytest.fixture(autouse=True)
def _desactivar_al_terminar() -> Iterator[None]:
    yield
    kill_switch.desactivar("test-cleanup")


def test_activar_desactivar_y_callable_para_politica() -> None:
    assert kill_switch.leer() is False

    kill_switch.activar("ana@equipo", "mantenimiento")
    assert kill_switch.leer() is True

    callable_politica = kill_switch.kill_switch_postgres()
    assert callable_politica() is True

    kill_switch.desactivar("ana@equipo")
    assert kill_switch.leer() is False
    assert callable_politica() is False  # lee en cada llamada, no cachea
