"""Linea base manual guiada (H2 y H3): un operador resuelve la MISMA falla que el agente,
con los runbooks y sin el agente, y el script mide con el mismo criterio.

Inicio: t2, la alerta de Grafana disparada. Fin: t5, la senal sana vista por el mismo
verificador externo que usa el agente. Si en 15 minutos no se recupera, el caso se registra
como no resuelto: no se descarta. La accion se clasifica con la Tabla 15 de la tesis.

Corre en el host, desde la raiz, con el laboratorio levantado:

    python -m scripts.linea_base --categoria pod_fallido --operador ana \
        --salida resultados/linea_base.csv
    python -m scripts.linea_base --categoria pod_fallido/config_invalida --operador ana
"""

from __future__ import annotations

import argparse
import csv
import time
from pathlib import Path

from domain.aiops_core.evaluacion import INCORRECTOS, ResultadoAccion
from scripts.experimento import (
    ESCENARIOS,
    RAIZ,
    VARIANTES,
    VENTANA_SEGUIMIENTO_S,
    VerificadorExterno,
    _esperar,
    _estado_regla,
    _k8s_sano,
    _prom,
    _sh,
    esperar_estable,
)

COLUMNAS = [
    "categoria",
    "variante",
    "mttr_s",
    "resultado",
    "accion_incorrecta",
    "operador",
    "notas",
]
ESPERA_ALERTA_S = 120.0


def escribir_fila(
    salida: Path,
    clave: str,
    mttr_s: float | None,
    resultado: ResultadoAccion,
    operador: str,
    notas: str,
) -> None:
    salida.parent.mkdir(parents=True, exist_ok=True)
    nuevo = not salida.exists()
    categoria, _, variante = clave.partition("/")
    with salida.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS)
        if nuevo:
            w.writeheader()
        w.writerow(
            {
                "categoria": categoria,
                "variante": variante,
                "mttr_s": "" if mttr_s is None else f"{mttr_s:.1f}",
                "resultado": resultado.value,
                "accion_incorrecta": "true" if resultado in INCORRECTOS else "false",
                "operador": operador,
                "notas": notas,
            }
        )


def _esperar_t2(alertname: str) -> float | None:
    limite = time.time() + ESPERA_ALERTA_S
    while time.time() < limite:
        if _estado_regla(alertname) == "firing":
            return time.time()
        time.sleep(1)
    return None


def _preguntar_resultado() -> ResultadoAccion:
    opciones = list(ResultadoAccion)
    for i, r in enumerate(opciones, 1):
        print(f"  {i}. {r.value}")
    while True:
        elegido = input("Resultado de tu accion (Tabla 15): ").strip()
        if elegido.isdigit() and 1 <= int(elegido) <= len(opciones):
            return opciones[int(elegido) - 1]


def medir(clave: str, operador: str, salida: Path) -> int:
    esc = {**ESCENARIOS, **VARIANTES}[clave]
    if esc.usa_k8s and not _k8s_sano():
        print("ERROR: el API server de Kubernetes no responde")
        return 1
    if esc.recuperar and _prom(esc.anomalia):  # partir de sano, como el agente
        _sh(["sh", f"scripts/fallas/{esc.recuperar}"], reintentos=3)
    if esc.recuperar and not esperar_estable(esc.sana):
        print("ERROR: el servicio no se mantuvo sano antes de la corrida")
        return 1
    inyeccion = _sh(["sh", f"scripts/fallas/{esc.falla}"], reintentos=3)
    if inyeccion.returncode != 0:
        print(f"ERROR: no se pudo inyectar la falla: {inyeccion.stderr.strip()[-200:]}")
        return 1
    if not _esperar(esc.anomalia, 180):
        print("ERROR: la falla no se manifesto en Prometheus")
        return 1
    t2 = _esperar_t2(esc.alertname)
    if t2 is None:
        print("ERROR: Grafana no disparo la alerta: corrida no valida")
        if esc.recuperar:
            _sh(["sh", f"scripts/fallas/{esc.recuperar}"], reintentos=3)
        return 1
    verificador = VerificadorExterno(esc.sana)
    verificador.start()
    print(
        f"\nALERTA DISPARADA: {esc.alertname} en {esc.servicio}. El cronometro corre.\n"
        f"Resuelvela como lo harias normalmente (runbooks en {RAIZ / 'agents/aiops/runbooks'}).\n"
        f"Si la accion no corresponde, escala. Limite: {VENTANA_SEGUIMIENTO_S / 60:.0f} min."
    )
    t5 = verificador.esperar(t2 + VENTANA_SEGUIMIENTO_S)
    mttr = None if t5 is None else t5 - t2
    print("\nNo resuelto en la ventana." if mttr is None else f"\nResuelto en {mttr:.0f} s.")
    resultado = _preguntar_resultado()
    notas = input("Notas (opcional): ").strip()
    if esc.recuperar and ("/" in clave or _prom(esc.anomalia)):
        _sh(["sh", f"scripts/fallas/{esc.recuperar}"], reintentos=3)
    escribir_fila(salida, clave, mttr, resultado, operador, notas)
    print(f"Registrado en {salida}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Linea base manual guiada.")
    p.add_argument("--categoria", required=True, choices=sorted({**ESCENARIOS, **VARIANTES}))
    p.add_argument("--operador", required=True)
    p.add_argument("--salida", default="resultados/linea_base.csv")
    args = p.parse_args()
    return medir(args.categoria, args.operador, Path(args.salida))


if __name__ == "__main__":
    raise SystemExit(main())
