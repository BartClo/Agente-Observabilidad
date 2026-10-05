"""POST /webhooks/grafana contra Redis real (profile `redis`: `docker compose
--profile redis up -d redis`). No corre el worker: solo confirma que el payload se
parsea, se dedupe y se encola de verdad en RQ -- no que el agente LLM lo resuelva
(eso necesita ANTHROPIC_API_KEY, ver agents/aiops/worker_jobs.py)."""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

os.environ["AIOPS_API_TOKEN"] = "test-token"

from app.api import app  # noqa: E402  (despues de fijar AIOPS_API_TOKEN de arriba)
from infra.queue import get_queue  # noqa: E402
from infra.redis_client import get_redis  # noqa: E402

HEADERS = {"Authorization": "Bearer test-token"}

try:
    get_redis().ping()
except Exception as _exc:  # cualquier fallo de conexion = skip el archivo entero
    pytestmark = pytest.mark.skip(
        f"redis no disponible ({_exc}): levantar el profile redis "
        "(`docker compose --profile redis up -d redis`) antes de correr este archivo."
    )

PAYLOAD = {
    "alerts": [
        {
            "status": "firing",
            "labels": {
                "alertname": "ServiceDown",
                "service": "checkout",
                "env": "staging",
                "severity": "critical",
            },
            "annotations": {"summary": "caido"},
            "startsAt": "2026-10-05T10:00:00Z",
            "fingerprint": "f1",
        }
    ]
}


@pytest.fixture(autouse=True)
def _limpiar_cola() -> Iterator[None]:
    yield
    get_queue("aiops").empty()  # type: ignore[no-untyped-call]  # rq sin stubs


def test_webhook_encola_un_job_por_alerta() -> None:
    cliente = TestClient(app)
    resp = cliente.post("/webhooks/grafana", headers=HEADERS, json=PAYLOAD)
    assert resp.status_code == 200
    body = resp.json()
    assert body["encolados"] == ["ServiceDown:checkout:f1"]
    assert body["deduplicados"] == []

    job = get_queue("aiops").fetch_job("aiops-webhook-ServiceDown_checkout_f1")
    assert job is not None
    assert job.get_status() == "queued"
    assert job.args[1] is True  # es_firing


def test_webhook_sin_token_rechaza() -> None:
    assert TestClient(app).post("/webhooks/grafana", json=PAYLOAD).status_code == 401


def test_webhook_dedupe_mismo_disparo_no_duplica() -> None:
    cliente = TestClient(app)
    cliente.post("/webhooks/grafana", headers=HEADERS, json=PAYLOAD)
    resp = cliente.post("/webhooks/grafana", headers=HEADERS, json=PAYLOAD)
    assert resp.json() == {"encolados": [], "deduplicados": ["ServiceDown:checkout:f1"]}
    assert get_queue("aiops").count == 1


def test_webhook_resolved_encola_tambien() -> None:
    payload_resuelto = {
        "alerts": [{**PAYLOAD["alerts"][0], "status": "resolved", "fingerprint": "f2"}]
    }
    resp = TestClient(app).post("/webhooks/grafana", headers=HEADERS, json=payload_resuelto)
    body = resp.json()
    assert body["encolados"] == ["ServiceDown:checkout:f2"]
    job = get_queue("aiops").fetch_job("aiops-webhook-ServiceDown_checkout_f2")
    assert job is not None and job.args[1] is False  # es_firing=False
