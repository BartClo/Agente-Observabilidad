"""Mimir, Thanos o Grafana Cloud: cada backend recibe su credencial y nada mas."""

from __future__ import annotations

import io
import urllib.request
from typing import Any

import pytest

from infra.observabilidad import PrometheusLoki


def test_cada_backend_recibe_su_credencial(monkeypatch: pytest.MonkeyPatch) -> None:
    pedidos: list[Any] = []

    def abrir(self: Any, pedido: Any, timeout: float = 0) -> io.BytesIO:
        pedidos.append(pedido)
        return io.BytesIO(b"{}")

    monkeypatch.setattr(urllib.request.OpenerDirector, "open", abrir)
    obs = PrometheusLoki(
        "http://prom", "http://loki", auth_prometheus="Bearer P", auth_loki="Basic L", org_id="t1"
    )
    obs.metrica("web", "up")
    obs.logs("web", 5)
    assert pedidos[0].get_header("Authorization") == "Bearer P"
    assert pedidos[1].get_header("Authorization") == "Basic L"
    assert all(p.get_header("X-scope-orgid") == "t1" for p in pedidos)


def test_con_credencial_no_sigue_redirecciones() -> None:
    from infra.observabilidad import _SinRedireccion

    assert _SinRedireccion().redirect_request() is None  # type: ignore[func-returns-value]


def test_la_credencial_viene_del_entorno(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AIOPS_PERFIL", raising=False)
    monkeypatch.setenv("AIOPS_PROMETHEUS_URL", "http://prom")
    monkeypatch.setenv("AIOPS_PROMETHEUS_AUTH", "Bearer S")
    obs = PrometheusLoki.desde_entorno()
    assert obs._auth_prom == "Bearer S"
    assert "Bearer S" not in repr(obs)
