"""TestClient contra app/api.py, en modo AIOPS_PERSISTENCIA=postgres (el que importa
probar: memoria es trivial y no ejercita el cruce API/Postgres). Requiere `make
migrate` (lo mismo que tests/test_infra_incidentes_postgres.py)."""

from __future__ import annotations

import os
from collections.abc import Iterator

import psycopg
import pytest
from fastapi.testclient import TestClient

from agents.aiops import runtime
from domain.aiops_core.modelos import NivelAutonomia

os.environ["AIOPS_API_TOKEN"] = "test-token"

from app.api import app  # noqa: E402  (despues de fijar AIOPS_API_TOKEN de arriba)

HEADERS = {"Authorization": "Bearer test-token"}

_ENV_TEMPORALES = ("AIOPS_PERSISTENCIA", "AIOPS_AUTONOMY_LEVEL", "AIOPS_SIM_FAULTS")


@pytest.fixture
def cliente() -> Iterator[TestClient]:
    runtime.reset()
    os.environ["AIOPS_PERSISTENCIA"] = "postgres"
    os.environ["AIOPS_AUTONOMY_LEVEL"] = str(int(NivelAutonomia.AUTONOMO_BAJO_RIESGO))
    os.environ["AIOPS_SIM_FAULTS"] = "servicio_detenido:checkout"
    yield TestClient(app)
    runtime.reset()
    for var in _ENV_TEMPORALES:
        os.environ.pop(var, None)
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        conn.execute("DELETE FROM aiops_incidentes")
        conn.execute("DELETE FROM aiops_eventos_auditoria")
        conn.execute(
            "UPDATE aiops_kill_switch SET activo=false, usuario=NULL, motivo=NULL WHERE id=true"
        )


def test_salud_no_requiere_token() -> None:
    assert TestClient(app).get("/salud").json() == {"estado": "ok"}


def test_endpoints_protegidos_exigen_token(cliente: TestClient) -> None:
    assert cliente.get("/incidentes").status_code == 401
    assert cliente.get("/incidentes", headers={"Authorization": "Bearer malo"}).status_code == 401
    assert cliente.get("/incidentes", headers=HEADERS).status_code == 200


def test_listar_y_ver_incidente(cliente: TestClient) -> None:
    ciclo = runtime.get_ciclo()
    alerta_id = ciclo.alertas_activas()[0].split(" | ")[0]
    inc = ciclo.abrir(alerta_id)
    ciclo.confirmar_anomalia(inc.id)

    listado = cliente.get("/incidentes", headers=HEADERS).json()
    assert [i["id"] for i in listado] == [inc.id]

    detalle = cliente.get(f"/incidentes/{inc.id}", headers=HEADERS).json()
    assert detalle["id"] == inc.id
    assert any(e["tipo"] == "confirmacion" for e in detalle["linea_de_tiempo"])

    assert cliente.get("/incidentes/INC-no-existe", headers=HEADERS).status_code == 404


def test_aprobar_y_rechazar(cliente: TestClient) -> None:
    ciclo = runtime.get_ciclo()
    alerta_id = ciclo.alertas_activas()[0].split(" | ")[0]
    inc_id = ciclo.abrir(alerta_id).id
    ciclo.confirmar_anomalia(inc_id)
    categoria, _, _ = ciclo.clasificar(inc_id)
    assert categoria is not None
    ciclo.registrar_diagnostico(inc_id, "causa", 0.9, categoria.runbook_id)

    resp = cliente.post(f"/incidentes/{inc_id}/aprobar", headers=HEADERS, json={})
    assert resp.status_code == 422  # falta usuario
    resp = cliente.post(
        f"/incidentes/{inc_id}/aprobar", headers=HEADERS, json={"usuario": "ana@equipo"}
    )
    assert resp.json() == {"estado": "aprobado"}
    assert ciclo.incidente(inc_id).aprobacion is not None

    resp = cliente.post(
        f"/incidentes/{inc_id}/rechazar",
        headers=HEADERS,
        json={"usuario": "ana@equipo", "motivo": "mejor no"},
    )
    assert resp.json()["estado"] == "rechazado"
    assert ciclo.incidente(inc_id).estado.value == "escalado"

    assert (
        cliente.post(
            "/incidentes/INC-no-existe/aprobar", headers=HEADERS, json={"usuario": "x"}
        ).status_code
        == 404
    )


def test_kill_switch(cliente: TestClient) -> None:
    assert cliente.get("/kill-switch", headers=HEADERS).json() == {"activo": False}
    payload = {"usuario": "ana@equipo", "activo": True, "motivo": "m"}
    resp = cliente.post("/kill-switch", headers=HEADERS, json=payload)
    assert resp.json() == {"activo": True}
    assert cliente.get("/kill-switch", headers=HEADERS).json() == {"activo": True}
    cliente.post("/kill-switch", headers=HEADERS, json={"usuario": "ana@equipo", "activo": False})
    assert cliente.get("/kill-switch", headers=HEADERS).json() == {"activo": False}


def test_metricas_y_metrics_prometheus(cliente: TestClient) -> None:
    ciclo = runtime.get_ciclo()
    alerta_id = ciclo.alertas_activas()[0].split(" | ")[0]
    inc_id = ciclo.abrir(alerta_id).id
    ciclo.confirmar_anomalia(inc_id)
    categoria, _, _ = ciclo.clasificar(inc_id)
    assert categoria is not None
    ciclo.registrar_diagnostico(inc_id, "causa", 0.9, categoria.runbook_id)
    ciclo.ejecutar_remediacion(inc_id, aprobada=False)
    ciclo.verificar(inc_id)
    ciclo.cerrar(inc_id)

    metricas = cliente.get("/metricas", headers=HEADERS).json()
    assert metricas["total_incidentes"] == 1
    assert metricas["tra"] == 100.0

    prom = cliente.get("/metrics")  # sin token: lo scrapea Prometheus
    assert prom.status_code == 200
    assert 'aiops_incidentes_total{estado="resuelto"} 1' in prom.text
    assert "aiops_tra_ratio 100.0" in prom.text


def test_ui_se_sirve_sin_token_con_csp_de_framing() -> None:
    """Fase 5: la pagina no trae datos (los pide con el token del operador), asi que
    se sirve sin token; frame-ancestors limita quien la puede embeber."""
    resp = TestClient(app).get("/ui")
    assert resp.status_code == 200
    assert "AIOps" in resp.text
    csp = resp.headers["content-security-policy"]
    assert "frame-ancestors" in csp and "http://localhost:3001" in csp
    assert "Bearer" in resp.text and "textContent" in resp.text  # token por cabecera, sin innerHTML
    assert "innerHTML" not in resp.text


def test_resumen_trae_aprobacion_y_metrics_trae_acciones(cliente: TestClient) -> None:
    ciclo = runtime.get_ciclo()
    alerta_id = ciclo.alertas_activas()[0].split(" | ")[0]
    inc_id = ciclo.abrir(alerta_id).id
    ciclo.confirmar_anomalia(inc_id)
    categoria, _, _ = ciclo.clasificar(inc_id)
    assert categoria is not None
    ciclo.registrar_diagnostico(inc_id, "causa", 0.9, categoria.runbook_id)
    ciclo.aprobar(inc_id, "ana@equipo")
    ciclo.ejecutar_remediacion(inc_id, aprobada=True)

    resumen = cliente.get("/incidentes", headers=HEADERS).json()[0]
    assert resumen["aprobacion"] == "aprobado"
    assert resumen["abierto_en"] > 0

    prom = cliente.get("/metrics").text
    assert 'aiops_acciones_total{accion="restart_service",ok="true"} 1' in prom


def test_rotacion_de_token_sin_corte(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fase 6: AIOPS_API_TOKEN acepta varios tokens separados por coma, para rotar
    sin cortar (viejo y nuevo validos mientras se actualiza el contact point de
    Grafana). Un token vacio en la lista nunca autentica."""
    monkeypatch.setenv("AIOPS_API_TOKEN", "viejo, nuevo,")
    c = TestClient(app)
    for token, esperado in (("viejo", 200), ("nuevo", 200), ("otro", 401), ("", 401)):
        r = c.get("/kill-switch", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == esperado, token
    assert c.get("/kill-switch", headers={"Authorization": "viejo"}).status_code == 401
