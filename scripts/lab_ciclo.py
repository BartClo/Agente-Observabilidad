"""Recorre el ciclo L1 completo sin LLM contra los backends reales del laboratorio
(Prometheus + Kubernetes), en el mismo orden que agents/aiops/prompt.md. Sirve para:

- probar la remediacion real de la Fase 4 sin depender de ANTHROPIC_API_KEY;
- tener una corrida determinista (el "diagnostico" lo fija este script, no un LLM),
  util como linea de comparacion en la Fase 7.

Uso (dentro del contenedor app, ver k8s-lab/README.md para las variables):
    uv run python -m scripts.lab_ciclo PodFailed api
"""

from __future__ import annotations

import sys
import time

from agents.aiops import runtime
from domain.aiops_core.catalogo import categoria_para_alerta
from domain.aiops_core.modelos import Alerta, Severidad


def main(alertname: str, servicio: str) -> int:
    ciclo = runtime.armar()
    alerta = Alerta(
        id=f"{alertname}:{servicio}:lab-{int(time.time())}",
        nombre=alertname,
        servicio=servicio,
        entorno="dev",
        severidad=Severidad.ALTA,
        resumen="disparada por scripts/lab_ciclo.py",
        disparada_en=time.time(),
    )
    inc = ciclo.abrir_desde_alerta(alerta)
    print("abierto:", inc.id)

    confirmada, detalle = ciclo.confirmar_anomalia(inc.id)
    print("confirmacion:", detalle)
    if not confirmada:
        print(ciclo.escalar(inc.id, f"anomalia no confirmada: {detalle}"))
        return 1

    categoria, elegible, motivos = ciclo.clasificar(inc.id)
    estado = "elegible" if elegible else motivos
    print("clasificacion:", categoria.id if categoria else None, estado)
    if not elegible or categoria is None:
        print(ciclo.escalar(inc.id, f"no elegible: {motivos}"))
        return 1

    cat = categoria_para_alerta(alertname)
    assert cat is not None
    ciclo.registrar_diagnostico(inc.id, f"falla de {cat.nombre} (lab)", 0.9, cat.runbook_id)

    t0 = time.time()
    res = ciclo.ejecutar_remediacion(inc.id, aprobada=False)
    print("remediacion:", res.mensaje)
    if not res.ejecutada:
        print(ciclo.escalar(inc.id, res.mensaje))
        return 1

    ok, detalle = ciclo.verificar(inc.id)
    print(f"verificacion ({time.time() - t0:.0f}s):", detalle)
    if not ok:
        print(ciclo.escalar(inc.id, f"no recuperado: {detalle}"))
        return 1

    cerrado = ciclo.cerrar(inc.id)
    print(f"CERRADO {cerrado.id} resuelto_autonomo={cerrado.resuelto_autonomo}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
