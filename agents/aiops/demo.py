"""Demo end-to-end con LLM sobre el banco simulado: el orquestador delega en `aiops`,
que atiende todas las alertas activas. Requiere ANTHROPIC_API_KEY.

    make aiops-demo

`make aiops-demo` corre en autonomia 3 (sin pausas de aprobacion); se cambia con
`make aiops-demo AIOPS_DEMO_LEVEL=1`. Para la tool con
aprobacion (nivel 2) hace falta un checkpointer y reanudar el grafo: queda para el
endpoint/UI.
"""

from __future__ import annotations

import os

os.environ.setdefault("AIOPS_AUTONOMY_LEVEL", "3")

from agents.aiops.runtime import get_ciclo  # noqa: E402
from app.main import build_agent  # noqa: E402
from domain.aiops_core import metricas  # noqa: E402

PEDIDO = (
    "Atiende todas las alertas activas de monitoreo, una por una, hasta cerrarlas o escalarlas."
)


def main() -> None:
    agent = build_agent()
    result = agent.invoke({"messages": [{"role": "user", "content": PEDIDO}]})
    print(result["messages"][-1].content)
    incidentes = get_ciclo().incidentes()
    print("\n--- Resultado medido ---")
    for inc in incidentes:
        print(f"{inc.id}: {inc.estado} (autonomo={inc.resuelto_autonomo})")
    try:
        print(f"TRA: {metricas.tasa_resolucion_autonoma(incidentes):.1f}%")
    except ValueError as exc:
        print(f"TRA: {exc}")


if __name__ == "__main__":
    main()
