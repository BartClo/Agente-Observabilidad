"""AIOPS_INTAKE_SERVICES: una alerta ajena no llega a la cola; sin la variable entran todas."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agents.aiops.worker_jobs import encolar_alerta
from domain.aiops_core.modelos import Alerta, Severidad


@pytest.mark.parametrize(
    ("lista", "servicio", "entra"),
    [
        ("qa-agent, owner-agent", "qa-agent", True),
        ("qa-agent, owner-agent", "owner-agent", True),
        ("qa-agent, owner-agent", "orchestrator", False),
        ("qa-agent", "qa-agent-2", False),
        ("", "orchestrator", True),
        (None, "orchestrator", True),
    ],
)
@pytest.mark.parametrize("es_firing", [True, False])
def test_filtro_de_entrada(
    monkeypatch: pytest.MonkeyPatch, lista: str | None, servicio: str, entra: bool, es_firing: bool
) -> None:
    encolados: list[object] = []
    cola = SimpleNamespace(fetch_job=lambda _id: None, enqueue=lambda *a, **k: encolados.append(a))
    monkeypatch.setattr("infra.queue.get_queue", lambda _n: cola)
    monkeypatch.delenv("AIOPS_INTAKE_SERVICES", raising=False)
    if lista is not None:
        monkeypatch.setenv("AIOPS_INTAKE_SERVICES", lista)
    alerta = Alerta(
        id=f"X:{servicio}",
        nombre="X",
        servicio=servicio,
        entorno="dev",
        severidad=Severidad.CRITICA,
        resumen="",
    )
    assert encolar_alerta(alerta, es_firing) is entra
    assert len(encolados) == int(entra)
