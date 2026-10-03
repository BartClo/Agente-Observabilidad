"""El agente `aiops` carga por el loader como cualquier otro, sin tocar app/."""

from __future__ import annotations

from app import loader


def test_aiops_carga_con_tools_rag_y_aprobacion() -> None:
    aiops = next(s for s in loader.load_subagents() if s["name"] == "aiops")
    nombres = {getattr(t, "__name__", "") for t in aiops["tools"]}
    assert {"abrir_incidente", "ejecutar_remediacion", "cerrar_incidente"} <= nombres
    assert "buscar_documentos" in nombres  # tool de rag sobre aiops_runbooks
    assert aiops["interrupt_on"] == {"ejecutar_remediacion_con_aprobacion": True}
    assert aiops["skills"] and aiops["skills"][0].endswith("ciclo-l1")
