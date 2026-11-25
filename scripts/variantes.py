"""Variantes confusoras en el laboratorio Docker: agente contra reglas (protocolo 6.6).

La alerta y la categoria son las de una falla limpia, pero reiniciar no corrige la causa. El
agente NO cambia: solo se agregan inyecciones y el envio de los logs de los contenedores a Loki
(en QA ya existe). Criterios: docs/variantes-docker.md (sellado antes de correr).

    python -m scripts.variantes --salida resultados/variantes-docker.csv --tope-usd 6
"""

from __future__ import annotations

import argparse
import calendar
import csv
import json
import random
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

from scripts import experimento as ex

LOKI = "http://localhost:3100/loki/api/v1/push"
SEMILLA = 20261125
# Cota conservadora, la misma que en QA (el precio oficial es menor): USD por millon.
USD_ENTRADA, USD_SALIDA = 4.0, 10.0
RESERVA_USD = 0.5  # no se parte una corrida si no cabe esto
SERVICIOS = ("lab-web", "lab-api", "lab-worker")

_WEB = 'max(iafactory_infra_container_health_status{service_name="lab-web"}) < 1'
_API = 'max(iafactory_infra_container_health_status{service_name="lab-api"}) < 1'
_WORKER = 'max(probe_success{service="lab-worker"}) < 1'


def _esc(alerta: str, svc: str, falla: str, anomalia: str, cat: str) -> ex.Escenario:
    recuperar = f"variante_recuperar_{svc.removeprefix('lab-')}.sh"
    return ex.Escenario(alerta, svc, falla, anomalia, recuperar, categoria=cat, plataforma="docker")


VARIANTES = {
    "config_invalida": _esc(
        "ContainerStopped", "lab-web", "variante_config_invalida.sh", _WEB, "contenedor_fallido"
    ),
    "comando_inexistente": _esc(
        "ContainerStopped", "lab-api", "variante_comando_inexistente.sh", _API, "contenedor_fallido"
    ),
    "variable_ausente": _esc(
        "ServiceDown", "lab-worker", "variante_variable_ausente.sh", _WORKER, "servicio_caido"
    ),
    "dependencia_caida": _esc(
        "ServiceDown", "lab-worker", "variante_dependencia_caida.sh", _WORKER, "servicio_caido"
    ),
    # Control: aqui reiniciar SI es lo correcto (detecta un agente que se abstiene de todo).
    "control_limpio": _esc(
        "ContainerStopped", "lab-web", "docker_contenedor_detenido.sh", _WEB, "contenedor_fallido"
    ),
}


def plan(repeticiones: int) -> list[tuple[int, str, str]]:
    """Bloques con todas las variantes en ambas condiciones, sorteados dentro del bloque."""
    azar = random.Random(SEMILLA)  # noqa: S311
    orden: list[tuple[int, str, str]] = []
    for n in range(1, repeticiones + 1):
        bloque = [(n, v, m) for v in VARIANTES for m in ("llm", "script")]
        azar.shuffle(bloque)
        orden += bloque
    return orden


def cota_usd(entrada: int, salida: int) -> float:
    return (entrada * USD_ENTRADA + salida * USD_SALIDA) / 1e6


def lineas_loki(salida: str) -> list[list[str]]:
    """`docker logs -t` -> [[ns, linea]]. Reenviar lo mismo no duplica: Loki descarta
    el par (marca, linea) repetido."""
    valores = []
    for cruda in salida.splitlines():
        marca, _, texto = cruda.partition(" ")
        base, _, frac = marca.rstrip("Z").partition(".")
        try:
            seg = calendar.timegm(time.strptime(base, "%Y-%m-%dT%H:%M:%S"))
        except ValueError:
            continue
        valores.append([f"{seg}{frac.ljust(9, '0')[:9]}", texto])
    return valores


def enviar_logs(parar: threading.Event) -> None:
    while not parar.wait(3):
        for s in SERVICIOS:
            try:
                r = subprocess.run(
                    ["docker", "logs", "-t", "--since", "5m", f"ia-factory-{s}"],
                    capture_output=True,
                    text=True,
                    timeout=20,
                )
                valores = lineas_loki(r.stdout + r.stderr) if r.returncode == 0 else []
                if not valores:
                    continue
                cuerpo = {"streams": [{"stream": {"service": s, "env": "dev"}, "values": valores}]}
                pedido = urllib.request.Request(  # noqa: S310
                    LOKI, json.dumps(cuerpo).encode(), {"Content-Type": "application/json"}
                )
                urllib.request.urlopen(pedido, timeout=10).close()  # noqa: S310
            except (OSError, subprocess.SubprocessError) as exc:
                print(f"  aviso logs {s}: {exc}", flush=True)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--salida", required=True)
    p.add_argument("--repeticiones", type=int, default=3)
    p.add_argument("--tope-usd", type=float, required=True)
    p.add_argument("--modo", choices=("ambos", "script"), default="ambos")
    p.add_argument("--fase", choices=("ajuste", "final"), default="final")
    args = p.parse_args()
    if ex._prom("up") is None:
        raise SystemExit("Prometheus no responde")
    salida = Path(args.salida)
    if salida.exists():
        raise SystemExit(f"{salida} ya existe: no se mezclan ni se pisan corridas")
    if args.fase == "final" and ex._git_salida("status", "--porcelain", "--untracked-files=no"):
        raise SystemExit("Hay cambios sin commitear")
    detalle = salida.with_suffix(".jsonl")
    ex.ESCENARIOS.update(VARIANTES)
    gastado = 0.0
    parar = threading.Event()
    threading.Thread(target=enviar_logs, args=(parar,), daemon=True).start()
    with (
        salida.open("w", encoding="utf-8", newline="") as f,
        detalle.open("w", encoding="utf-8") as g,
        ex.host_docker(),
    ):
        w = csv.DictWriter(f, fieldnames=["variante", *ex.COLUMNAS])
        w.writeheader()
        for i, (n, variante, modo) in enumerate(plan(args.repeticiones), 1):
            if args.modo == "script" and modo == "llm":
                continue
            if modo == "llm" and gastado + RESERVA_USD > args.tope_usd:
                print(f"[{i}] TOPE: {gastado:.2f} USD en cota; se omite {variante} llm", flush=True)
                continue
            print(f"[{i}] {variante} {modo} rep {n} (cota {gastado:.2f} USD)", flush=True)
            fila = ex.correr(variante, n, modo, 3, "", args.fase)
            w.writerow({"variante": variante, **fila})
            f.flush()
            if fila["incidente"]:
                d = ex._incidente(str(fila["incidente"]))
                reg = {"variante": variante, "modo": modo, "rep": n, "incidente": d}
                g.write(json.dumps(reg, ensure_ascii=False) + "\n")
                g.flush()
            tokens = [int(str(fila[c] or 0)) for c in ("tokens_entrada", "tokens_salida")]
            gastado += cota_usd(*tokens)
            if modo == "llm" and not any(tokens):
                gastado += RESERVA_USD  # sin costo registrado: se asume el peor caso
    parar.set()
    print(f"Listo: {salida} (cota {gastado:.2f} USD)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
