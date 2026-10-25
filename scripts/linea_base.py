"""Linea base manual guiada (H2 y H3): un operador resuelve la MISMA falla que el agente,
con los runbooks y sin el agente, y el script mide el tiempo con el mismo criterio.

Inicio: el instante en que la anomalia es visible en Prometheus (igual que `disparada_en`
del agente). Fin: cuando la anomalia deja de verse. El agente cierra DESPUES de su propia
verificacion, asi que este fin favorece levemente a la linea base: es conservador frente
a H2 y se declara en la tesis.

Corre en el host, desde la raiz, con el laboratorio levantado:

    python -m scripts.linea_base --categoria pod_fallido --operador ana \
        --salida resultados/linea_base.csv
"""

from __future__ import annotations

import argparse
import csv
import time
from pathlib import Path

from scripts.experimento import ESCENARIOS, RAIZ, _esperar, _k8s_sano, _prom, _sh

COLUMNAS = ["categoria", "mttr_s", "accion_incorrecta", "operador", "notas"]
LIMITE_S = 1800  # una resolucion manual que pasa de 30 min no es L1: se anula la corrida


def escribir_fila(
    salida: Path,
    categoria: str,
    mttr_s: float,
    incorrecta: bool,
    operador: str,
    notas: str,
) -> None:
    salida.parent.mkdir(parents=True, exist_ok=True)
    nuevo = not salida.exists()
    with salida.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS)
        if nuevo:
            w.writeheader()
        w.writerow(
            {
                "categoria": categoria,
                "mttr_s": f"{mttr_s:.1f}",
                "accion_incorrecta": "true" if incorrecta else "false",
                "operador": operador,
                "notas": notas,
            }
        )


def medir(categoria: str, operador: str, salida: Path) -> int:
    esc = ESCENARIOS[categoria]
    if esc.usa_k8s and not _k8s_sano():
        print("ERROR: el API server de k3d no responde")
        return 1
    if esc.recuperar and _prom(esc.anomalia):  # partir de sano, como el agente
        _sh(["sh", f"scripts/fallas/{esc.recuperar}"], reintentos=3)
        if not _esperar(esc.anomalia, 240, cumplida=False):
            print("ERROR: el servicio no volvio a sano antes de la corrida")
            return 1
    inyeccion = _sh(["sh", f"scripts/fallas/{esc.falla}"], reintentos=3)
    if inyeccion.returncode != 0:
        print(f"ERROR: no se pudo inyectar la falla: {inyeccion.stderr.strip()[-200:]}")
        return 1
    if not _esperar(esc.anomalia, 180):
        print("ERROR: la falla no se manifesto en Prometheus")
        return 1
    disparo = time.time()
    print(
        f"\nFALLA ACTIVA: {categoria} en {esc.servicio}. El cronometro corre.\n"
        f"Resuelvela como lo harias normalmente (runbooks en {RAIZ / 'agents/aiops/runbooks'}).\n"
        f"El tiempo termina cuando la alerta deja de verse (limite {LIMITE_S // 60} min)."
    )
    if not _esperar(esc.anomalia, LIMITE_S, cumplida=False):
        print("Pasaron 30 min sin resolver: corrida anulada, no se registra.")
        return 1
    mttr = time.time() - disparo
    print(f"\nResuelto en {mttr:.0f} s.")
    incorrecta = input("¿Ejecutaste alguna accion incorrecta o innecesaria? [s/N] ").strip().lower()
    notas = input("Notas (opcional): ").strip()
    escribir_fila(salida, categoria, mttr, incorrecta.startswith("s"), operador, notas)
    print(f"Registrado en {salida}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Linea base manual guiada.")
    p.add_argument("--categoria", required=True, choices=sorted(ESCENARIOS))
    p.add_argument("--operador", required=True)
    p.add_argument("--salida", default="resultados/linea_base.csv")
    args = p.parse_args()
    return medir(args.categoria, args.operador, Path(args.salida))


if __name__ == "__main__":
    raise SystemExit(main())
