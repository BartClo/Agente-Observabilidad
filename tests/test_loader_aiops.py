"""El agente `aiops` carga por el loader como cualquier otro, sin tocar app/."""

from __future__ import annotations

from app import loader


def test_aiops_carga_con_tools_y_aprobacion() -> None:
    aiops = next(s for s in loader.load_subagents() if s["name"] == "aiops")
    nombres = {getattr(t, "__name__", "") for t in aiops["tools"]}
    assert {"abrir_incidente", "ejecutar_remediacion", "cerrar_incidente"} <= nombres
    # El conocimiento es la tool propia buscar_conocimiento, no la generica del loader.
    assert "buscar_conocimiento" in nombres
    assert "buscar_documentos" not in nombres
    assert aiops["interrupt_on"] == {"ejecutar_remediacion_con_aprobacion": True}
    assert aiops["skills"] and aiops["skills"][0].endswith("ciclo-l1")


def test_texto_runbook_sin_frontmatter_y_solo_ids_validos() -> None:
    from agents.aiops.tools import texto_runbook

    rb = texto_runbook("RB-003")
    assert rb is not None and rb.startswith("# RB-003") and "recreate_pod" in rb
    assert "propietario:" not in rb  # frontmatter fuera
    assert texto_runbook("RB-999") is None
    assert texto_runbook("../../.env") is None  # nada de rutas arbitrarias
