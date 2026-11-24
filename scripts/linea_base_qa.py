"""Linea base humana en QA. Solo stdlib: se copia a la VM y la corre el OBSERVADOR.

    python3 linea_base_qa.py plan     # una vez: fija el orden al azar, antes de medir
    python3 linea_base_qa.py medir --operador OP1   # inyecta y mide las que falten

Inicio: up==0 visible en Prometheus. Aviso: la alerta pasa a firing. Fin: up==1.
Toda corrida inyectada se registra, tambien las que no se resuelven o se interrumpen.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import subprocess
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path

# Lista cerrada: sin estado segun el informe del 24-11. No agregar bases de datos ni colas.
SERVICIOS = ("qa-agent", "devops-agent", "architect-agent")
PROM = os.environ.get("QA_PROMETHEUS", "http://localhost:9090")
DOCKER = os.environ.get("QA_DOCKER", "sudo docker").split()
TIPOS = ("muerto", "congelado", "aislado", "transitoria")
LIMITE_S = 1800
VUELVE_SOLA_S = 60  # transitoria: vuelve 60 s despues del aviso, sin que nadie actue
PLAN, SALIDA, BITACORA = Path("plan_qa.json"), Path("linea_base_qa.csv"), Path("linea_base_qa.log")
COLUMNAS = (
    "n tipo servicio operador inyectada anomalia aviso contenedor_iniciado recuperado "
    "deteccion_s atencion_s mttr_s resultado accion_incorrecta notas"
).split()


def prom(consulta: str) -> list[float]:
    url = f"{PROM}/api/v1/query?" + urllib.parse.urlencode({"query": consulta})
    with urllib.request.urlopen(url, timeout=10) as r:
        return [float(s["value"][1]) for s in json.load(r)["data"]["result"]]


def docker(*args: str) -> str:
    r = subprocess.run([*DOCKER, *args], capture_output=True, text=True, timeout=60, check=True)
    return r.stdout.strip()


def log(texto: str) -> None:
    linea = f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {texto}"
    print(linea, flush=True)
    with BITACORA.open("a", encoding="utf-8") as f:
        f.write(linea + "\n")


def esperar(condicion: Callable[[], bool], limite: float) -> float | None:
    fin = time.time() + limite
    while time.time() < fin:
        try:
            if condicion():
                return time.time()
        except OSError as exc:
            log(f"[OBSERVADOR] Prometheus no respondio: {exc}")
        time.sleep(2)
    return None


def arriba(s: str) -> bool:
    return prom(f'up{{job="{s}"}}') == [1.0]


def inyectar(tipo: str, cont: str) -> list[str]:
    """Provoca la falla y devuelve el comando de Docker que la deshace."""
    if tipo == "congelado":
        deshacer = ["unpause", cont]
        docker("pause", cont)
    elif tipo == "aislado":
        redes = json.loads(docker("inspect", "-f", "{{json .NetworkSettings.Networks}}", cont))
        if len(redes) != 1:
            raise SystemExit(f"{cont} tiene {len(redes)} redes: no se aisla")
        red, datos = next(iter(redes.items()))
        if datos.get("IPAMConfig") or datos.get("DriverOpts"):
            raise SystemExit(f"{cont} tiene IP u opciones de red fijas: no se aisla")
        alias = [x for a in datos.get("Aliases") or [] for x in ("--alias", a)]
        deshacer = ["network", "connect", *alias, red, cont]
        docker("network", "disconnect", red, cont)
    else:
        deshacer = ["start", cont]
        docker("kill", cont)
    log(f"[FALLA]   {tipo} en {cont}. Para deshacer: docker {' '.join(deshacer)}")
    return deshacer


def correr(n: int, tipo: str, s: str, operador: str, preguntar: Callable[[str], str] = input) -> str:
    cont = f"ia-factory-{s}"
    if not arriba(s) or docker("inspect", "-f", "{{.State.Running}}", cont) != "true":
        raise SystemExit(f"{s} no esta sano: no se inyecta")
    f: dict[str, object] = dict.fromkeys(COLUMNAS, "")
    f.update(n=n, tipo=tipo, servicio=s, operador=operador, resultado="interrumpida")
    f["inyectada"] = f"{time.time():.0f}"
    anomalia: float | None = None
    aviso: float | None = None
    recuperado: float | None = None
    volvio_sola = False
    deshacer = inyectar(tipo, cont)
    try:
        anomalia = esperar(lambda: prom(f'up{{job="{s}"}}') == [0.0], 180)
        if anomalia is None:
            f["resultado"] = "sin_anomalia"
        else:
            log(f"[METRICA] #{n} up=0: corre el reloj")
            alerta = f'ALERTS{{alertname="AgentServiceDown",alertstate="firing",job="{s}"}}'

            def avanza() -> bool:
                nonlocal aviso, volvio_sola
                if aviso is None and prom(alerta):
                    aviso = time.time()
                    log(f"[ALERTA]  #{n} AgentServiceDown firing")
                if arriba(s):
                    return True
                if tipo == "transitoria" and not volvio_sola and aviso:
                    if time.time() - aviso >= VUELVE_SOLA_S:
                        docker(*deshacer)
                        volvio_sola = True
                        log(f"[FALLA]   #{n} vuelve sola")
                return False

            recuperado = esperar(avanza, LIMITE_S)
            f["resultado"] = "no_resuelta"
            if recuperado:
                f["resultado"] = "volvio_sola" if volvio_sola else "resuelta"
            log(f"[METRICA] #{n} {f['resultado']}")
            f["contenedor_iniciado"] = docker("inspect", "-f", "{{.State.StartedAt}}", cont)
    finally:
        # Ante limite, error o Ctrl-C el servicio no queda caido; la fila se guarda igual.
        if recuperado is None:
            try:
                docker(*deshacer)
                log(f"[OBSERVADOR] #{n} se deshizo la falla (no lo hizo el operador)")
            except (OSError, subprocess.SubprocessError) as exc:
                log(f"[OBSERVADOR] URGENTE: revisar {cont} a mano: {exc}")
        for k, t in (("anomalia", anomalia), ("aviso", aviso), ("recuperado", recuperado)):
            f[k] = f"{t:.0f}" if t else ""
        if anomalia and aviso:
            f["deteccion_s"] = f"{aviso - anomalia:.0f}"
        if recuperado and aviso and tipo != "transitoria":
            f["atencion_s"] = f"{recuperado - aviso:.0f}"
        if recuperado and anomalia and tipo != "transitoria":
            f["mttr_s"] = f"{recuperado - anomalia:.0f}"
        try:
            if f["resultado"] in ("resuelta", "volvio_sola", "no_resuelta"):
                f["accion_incorrecta"] = preguntar("Accion incorrecta (Tabla 14) [s/n]: ").strip()
                f["notas"] = preguntar("Que hizo el operador: ").strip()
        finally:
            nuevo = not SALIDA.exists()
            with SALIDA.open("a", encoding="utf-8", newline="") as h:
                w = csv.DictWriter(h, fieldnames=COLUMNAS)
                if nuevo:
                    w.writeheader()
                w.writerow(f)
    return str(f["resultado"])


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("modo", choices=("plan", "medir"))
    p.add_argument("--operador", default="OP1")
    p.add_argument("--servicio", choices=SERVICIOS, help="plan de ensayo: solo este servicio")
    p.add_argument("--repeticiones", type=int, default=4)
    a = p.parse_args()
    if a.modo == "plan":
        if PLAN.exists():
            raise SystemExit(f"{PLAN} ya existe: el orden no se vuelve a sortear")
        servicios = [a.servicio] if a.servicio else list(SERVICIOS)
        orden = []
        for tipo in TIPOS:  # cada tipo rota por los servicios
            inicio = random.randrange(len(servicios))
            for k in range(a.repeticiones):
                orden.append([tipo, servicios[(inicio + k) % len(servicios)]])
        random.shuffle(orden)
        pausas = [random.randint(600, 1500) for _ in orden]
        PLAN.write_text(json.dumps({"orden": orden, "pausas_s": pausas}), "utf-8")
        print(f"{len(orden)} fallas guardadas en {PLAN}. No mostrarlo al operador.")
        return
    plan = json.loads(PLAN.read_text("utf-8"))
    hechas = 0
    if SALIDA.exists():
        with SALIDA.open(encoding="utf-8", newline="") as h:
            hechas = len(list(csv.DictReader(h)))
    for i in range(hechas, len(plan["orden"])):
        time.sleep(plan["pausas_s"][i])
        r = correr(i + 1, *plan["orden"][i], a.operador)
        if r not in ("resuelta", "volvio_sola"):
            raise SystemExit(f"Corrida {i + 1}: {r}. Revisar antes de seguir.")


if __name__ == "__main__":
    main()
