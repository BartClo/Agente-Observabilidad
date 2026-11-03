"""Arranque del worker: reconcilia los incidentes que quedaron a medias antes de tomar
trabajos. Sin esto, un worker que murio a mitad de un incidente lo dejaba abierto hasta la
proxima alerta (que dispara el barrido) o hasta que alguien llamara a POST /reconciliar.

Es best-effort y SIEMPRE devuelve 0: el comando del compose encadena con `;` para que el
worker levante aunque Postgres todavia no responda.

    python -m agents.aiops.arranque
"""

from __future__ import annotations

from agents.aiops import runtime, worker_jobs
from domain.aiops_core.ciclo import Ciclo


def _ciclo() -> Ciclo:
    return runtime.armar(persistencia="postgres")


def main() -> int:
    try:
        tocados = worker_jobs.reconciliar_colgados(_ciclo())
        print(
            f"arranque: reconciliados {', '.join(tocados)}"
            if tocados
            else "arranque: ningun incidente colgado"
        )
    except Exception as exc:
        print(f"arranque: no se pudo reconciliar ({type(exc).__name__}); el worker sigue")
    try:
        from agents.aiops import jira_poller

        if jira_poller.programar(5):
            print("jira: sondeo agendado")
    except Exception as exc:
        print(f"jira: no se pudo agendar el sondeo ({type(exc).__name__}); el worker sigue")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
