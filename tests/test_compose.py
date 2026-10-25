"""Invariantes de despliegue que un test unitario normal no ve."""

from __future__ import annotations

from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parent.parent


def test_el_worker_corre_con_scheduler_porque_el_webhook_usa_reintentos_con_espera() -> None:
    """`Retry(interval=[...])` deja el job en estado `scheduled` y solo un worker con
    scheduler lo vuelve a encolar. Sin el, un job que falla una vez queda `scheduled` para
    siempre y el webhook (que deduplica por id de alerta y trata `scheduled` como en curso)
    ignora todas las alertas siguientes de esa huella. Hallado en vivo (2026-10-25)."""
    api = (RAIZ / "app" / "api.py").read_text(encoding="utf-8")
    assert "Retry(" in api and "interval=" in api
    compose = yaml.safe_load((RAIZ / "docker-compose.yml").read_text(encoding="utf-8"))
    comando = compose["services"]["worker"]["command"]
    assert "--with-scheduler" in comando
