"""Atiende UN incidente contra los backends reales del laboratorio (Prometheus +
Kubernetes). Lo usa scripts/experimento.py (Fase 7) y sirve para probar a mano.

Dos modos de "quien atiende":
- `script` (default): recorre el ciclo de agents/aiops/prompt.md con un diagnostico fijo.
  No necesita ANTHROPIC_API_KEY. Prueba la plomeria; NO mide al agente (su TRA es alta
  por construccion).
- `llm`: lo atiende el agente real (deepagents + LLM), con el mismo codigo que el worker
  (agents/aiops/worker_jobs.atender_con_agente). Es el modo que mide la tesis.

Al final imprime una linea `RESULTADO {json}` con el id del incidente: el resto
(estado, tiempos, acciones, tokens) se lee de la API, igual que lo veria un operador.

Uso (dentro del contenedor app, ver k8s-lab/README.md para las variables):
    uv run python -m scripts.lab_ciclo PodFailed api --modo script
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from agents.aiops import runtime
from domain.aiops_core.catalogo import categoria_para_alerta
from domain.aiops_core.ciclo import Ciclo
from domain.aiops_core.modelos import Alerta, Severidad
from domain.aiops_core.politicas import Veredicto


def _atender_script(ciclo: Ciclo, inc_id: str, alertname: str) -> None:
    confirmada, detalle = ciclo.confirmar_anomalia(inc_id)
    print("confirmacion:", detalle)
    if not confirmada:
        ciclo.escalar(inc_id, f"anomalia no confirmada: {detalle}")
        return

    categoria, elegible, motivos = ciclo.clasificar(inc_id)
    print(
        "clasificacion:", categoria.id if categoria else None, "elegible" if elegible else motivos
    )
    if not elegible or categoria is None:
        ciclo.escalar(inc_id, f"no elegible: {motivos}")
        return

    cat = categoria_para_alerta(alertname)
    assert cat is not None
    ciclo.registrar_diagnostico(inc_id, f"falla de {cat.nombre} (lab)", 0.9, cat.runbook_id)

    t0 = time.time()
    res = ciclo.ejecutar_remediacion(inc_id, aprobada=False)
    print("remediacion:", res.mensaje)
    if res.veredicto is Veredicto.APROBACION:
        # Nivel 2: lo que hace el agente pausado por interrupt_on, sin LLM. La decision
        # la registra un humano desde la UI (/ui -> POST /incidentes/{id}/aprobar), en
        # otro proceso: por eso exige AIOPS_PERSISTENCIA=postgres.
        print(f"esperando decision humana en la UI para {inc_id} ...", flush=True)
        while (aprob := ciclo.incidente(inc_id).aprobacion) is None:
            time.sleep(2)
        print(f"decision: {aprob.veredicto} por {aprob.usuario}")
        if aprob.veredicto != "aprobado":
            return  # rechazar() ya escalo el incidente
        t0 = time.time()  # medir la remediacion, no la espera humana
        res = ciclo.ejecutar_remediacion(inc_id, aprobada=True)
        print("remediacion (aprobada):", res.mensaje)
    if not res.ejecutada:
        ciclo.escalar(inc_id, res.mensaje)
        return

    ok, detalle = ciclo.verificar(inc_id)
    print(f"verificacion ({time.time() - t0:.0f}s):", detalle)
    if not ok:
        ciclo.escalar(inc_id, f"no recuperado: {detalle}")
        return
    ciclo.cerrar(inc_id)


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("alertname")
    p.add_argument("servicio")
    p.add_argument("--modo", choices=("script", "llm"), default="script")
    p.add_argument(
        "--disparada-en",
        type=float,
        default=None,
        help="epoch del disparo de la alerta (el MTTR se mide desde aca); default: ahora",
    )
    p.add_argument("--severidad", default="alta", choices=[s.value for s in Severidad])
    args = p.parse_args(argv)

    ciclo = runtime.armar()
    disparo = args.disparada_en if args.disparada_en is not None else time.time()
    alerta = Alerta(
        id=f"{args.alertname}:{args.servicio}:lab-{time.time_ns()}",
        nombre=args.alertname,
        servicio=args.servicio,
        entorno="dev",
        severidad=Severidad(args.severidad),
        resumen=f"disparada por scripts/lab_ciclo.py (modo {args.modo})",
        disparada_en=disparo,
    )
    inc = ciclo.abrir_desde_alerta(alerta)
    print("abierto:", inc.id, flush=True)

    error = None
    try:
        if args.modo == "llm":
            from agents.aiops.worker_jobs import atender_con_agente

            atender_con_agente(ciclo, inc.id, alerta)
        else:
            _atender_script(ciclo, inc.id, args.alertname)
    except Exception as exc:  # el experimento registra el fallo y sigue con la proxima corrida
        error = f"{type(exc).__name__}: {exc}"
        print("ERROR atendiendo:", error, flush=True)

    final = ciclo.incidente(inc.id)
    print(f"final: {final.id} estado={final.estado} autonomo={final.resuelto_autonomo}")
    print("RESULTADO " + json.dumps({"incidente": inc.id, "modo": args.modo, "error": error}))
    return 0 if error is None else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
