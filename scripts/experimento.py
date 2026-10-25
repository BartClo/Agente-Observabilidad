"""Experimento de la Fase 7: N corridas por categoria, una fila de CSV por corrida.

Cada corrida: (1) deja el servicio sano, (2) inyecta la falla con scripts/fallas/,
(3) espera a que la anomalia aparezca en Prometheus (= disparo de la alerta), (4) hace
atender el incidente (`--modo script` o `--modo llm`, ver scripts/lab_ciclo.py), (5) lee
el resultado de la API como lo veria un operador y (6) recupera el servicio.

Corre en el HOST (solo stdlib): orquesta docker compose, kubectl y la API. El ciclo
corre con `docker compose exec` en el contenedor `api`, que ya esta levantado: arrancar
un contenedor nuevo por corrida (1-2 min en esta maquina) inflaria el MTTR.

    python scripts/experimento.py --modo script --nivel 3 --repeticiones 3 \\
        --categorias pod_fallido,servicio_detenido --salida resultados/script-n3.csv

Despues: python -m scripts.analizar_experimento resultados/script-n3.csv
Protocolo completo: docs/protocolo-experimento.md
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PROMETHEUS = os.environ.get("EXP_PROMETHEUS", "http://localhost:9090")
API = os.environ.get("EXP_API", "http://localhost:8010")


@dataclass(frozen=True)
class Escenario:
    alertname: str
    servicio: str
    falla: str  # script en scripts/fallas/
    anomalia: str  # PromQL que da >0 resultados mientras la falla esta presente
    recuperar: str | None = None  # script para volver a sano entre corridas
    usa_k8s: bool = False


ESCENARIOS: dict[str, Escenario] = {
    "servicio_detenido": Escenario(
        "ServiceDown",
        "checkout",
        "servicio_detenido.sh",
        'max(up{service="checkout"}) < 1',
        "recuperar_servicio.sh",
        usa_k8s=True,
    ),
    "pod_fallido": Escenario(
        "PodFailed",
        "api",
        "pod_fallido.sh",
        'sum(kube_pod_status_ready{condition="true",pod=~"api-.*"}) < 1',
        "recuperar_pod.sh",
        usa_k8s=True,
    ),
    "disco_lleno": Escenario(
        "DiskUsageHigh",
        "billing",
        "disco_lleno.sh",
        '100 * max(1 - node_filesystem_avail_bytes{service="billing",mountpoint="/data"}'
        ' / node_filesystem_size_bytes{service="billing",mountpoint="/data"}) > 85',
        "recuperar_disco.sh",
    ),
    # Sin consumidor real ni metricas por cola: el agente escala por falta de datos.
    "cola_detenida": Escenario(
        "QueueStalled",
        "worker",
        "cola_detenida.sh",
        "max(rabbitmq_queue_consumers) < 1",
    ),
    # Sin accion autorizada: escala por diseno. La falla (cert de 3 dias) ya esta presente.
    "certificado_por_vencer": Escenario(
        "CertExpiringSoon",
        "gateway",
        "certificado_por_vencer.sh",
        '(min(probe_ssl_earliest_cert_expiry{service="gateway"}) - time()) / 86400 < 14',
    ),
}

COLUMNAS = [
    "corrida",
    "fecha",
    "modo",
    "fase",
    "nivel",
    "agente",
    "categoria_esperada",
    "alertname",
    "servicio",
    "incidente",
    "estado",
    "categoria_detectada",
    "elegible_agente",
    "resuelto_autonomo",
    "verificado",
    "acciones",
    "acciones_nombres",
    "disparada_en",
    "inicio_atencion",
    "cerrado_en",
    "mttr_s",
    "tokens_entrada",
    "tokens_salida",
    "turnos_llm",
    "llamadas_tools",
    "modelo_llm",
    "motivo_escalamiento",
    "error",
]

_ENV_SUB = {**os.environ, "MSYS_NO_PATHCONV": "1"}  # Git Bash: no traducir /paths


def _sh(
    args: list[str], timeout: float = 300, reintentos: int = 1
) -> subprocess.CompletedProcess[str]:
    ultimo: subprocess.CompletedProcess[str] | None = None
    for _ in range(reintentos):
        try:
            ultimo = subprocess.run(
                args, cwd=RAIZ, capture_output=True, text=True, timeout=timeout, env=_ENV_SUB
            )
        except subprocess.TimeoutExpired as exc:
            ultimo = subprocess.CompletedProcess(args, 124, "", f"timeout: {exc}")
        if ultimo.returncode == 0:
            return ultimo
        time.sleep(5)
    assert ultimo is not None
    return ultimo


def _prom(query: str) -> bool | None:
    """True si la query da resultados (la condicion se cumple), None si Prometheus falla."""
    url = f"{PROMETHEUS}/api/v1/query?" + urllib.parse.urlencode({"query": query})
    try:
        with urllib.request.urlopen(url, timeout=10) as r:  # noqa: S310
            return bool(json.load(r)["data"]["result"])
    except Exception:
        return None


def _esperar(condicion: str, timeout: float, cumplida: bool = True) -> bool:
    limite = time.time() + timeout
    while time.time() < limite:
        if _prom(condicion) is cumplida:
            return True
        time.sleep(3)
    return False


def _token_api() -> str:
    if tok := os.environ.get("AIOPS_API_TOKEN"):
        return tok.split(",")[0].strip()
    for linea in (RAIZ / ".env").read_text(encoding="utf-8").splitlines():
        if linea.startswith("AIOPS_API_TOKEN="):
            return linea.split("=", 1)[1].split(",")[0].strip()
    raise SystemExit("Falta AIOPS_API_TOKEN (entorno o .env)")


def _incidente(inc_id: str) -> dict[str, object]:
    req = urllib.request.Request(  # noqa: S310
        f"{API}/incidentes/{urllib.parse.quote(inc_id, safe='')}",
        headers={"Authorization": f"Bearer {_token_api()}"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310
        return dict(json.load(r))


def _puerto_k8s() -> str:
    salida = _sh(["docker", "port", "k3d-aiops-lab-serverlb"], timeout=30).stdout
    m = re.search(r"6443/tcp -> [\d.]+:(\d+)", salida)
    if not m:
        raise SystemExit("No encuentro el API server de k3d: k3d cluster start aiops-lab")
    return m.group(1)


def _k8s_sano() -> bool:
    return _sh(["kubectl", "get", "--raw", "/readyz"], timeout=40, reintentos=3).returncode == 0


def _env_ciclo(nivel: int, puerto: str) -> list[str]:
    env = {
        "AIOPS_BACKEND": "prometheus",
        "AIOPS_PROMETHEUS_URL": "http://prometheus:9090",
        # Logs (k8s-lab/promtail.yaml): explicito como Prometheus, para no depender de
        # que el contenedor haya releido el .env.
        "AIOPS_LOKI_URL": "http://loki:3100",
        # El experimento no avisa a Google Chat: serian cientos de mensajes. El .env del
        # contenedor si trae el webhook; aca se vacia a proposito.
        "AIOPS_GCHAT_WEBHOOK_URL": "",
        "AIOPS_ACTIONS": "k8s",
        "AIOPS_K8S_API": f"https://host.docker.internal:{puerto}",
        "AIOPS_K8S_TOKEN_FILE": "k8s-lab/.secrets/token",
        "AIOPS_K8S_CA_FILE": "k8s-lab/.secrets/ca.crt",
        "AIOPS_AUTONOMY_LEVEL": str(nivel),
        "AIOPS_ALLOWED_ENVS": "dev",
        "AIOPS_VERIFY_WINDOW_S": "180",
        "AIOPS_VERIFY_INTERVAL_S": "3",
        "AIOPS_CONFIRM_WINDOW_S": "30",
        "AIOPS_DISK_MOUNTPOINT": "/data",
        "AIOPS_PERSISTENCIA": "postgres",
        "PYTHONUNBUFFERED": "1",
        "AIOPS_AGENTE": os.environ.get("AIOPS_AGENTE", "unico"),
    }
    return [a for k, v in env.items() for a in ("-e", f"{k}={v}")]


def correr(
    cat: str, n: int, modo: str, nivel: int, puerto: str, fase: str = "ajuste"
) -> dict[str, object]:
    esc = ESCENARIOS[cat]
    fila: dict[str, object] = {c: "" for c in COLUMNAS}
    fila.update(
        corrida=n,
        fecha=time.strftime("%Y-%m-%dT%H:%M:%S"),
        modo=modo,
        fase=fase,
        nivel=nivel,
        agente=os.environ.get("AIOPS_AGENTE", "unico"),
        categoria_esperada=cat,
        alertname=esc.alertname,
        servicio=esc.servicio,
    )

    def fallo(msg: str) -> dict[str, object]:
        fila["error"] = msg
        print(f"  ERROR: {msg}")
        return fila

    if esc.usa_k8s and not _k8s_sano():
        return fallo("infra: API server de k3d no responde")
    # (1) partir de sano: si la falla anterior quedo, recuperar primero
    if esc.recuperar and _prom(esc.anomalia):
        _sh(["sh", f"scripts/fallas/{esc.recuperar}"], reintentos=3)
        if not _esperar(esc.anomalia, 240, cumplida=False):
            return fallo("infra: el servicio no volvio a sano antes de la corrida")
    # (2) inyectar y (3) esperar la anomalia
    r = _sh(["sh", f"scripts/fallas/{esc.falla}"], reintentos=3)
    if r.returncode != 0:
        return fallo(f"infra: no se pudo inyectar la falla: {r.stderr.strip()[-200:]}")
    if not _esperar(esc.anomalia, 180):
        return fallo("infra: la falla no se manifesto en Prometheus")
    disparo = time.time()
    fila["disparada_en"] = f"{disparo:.3f}"
    # (4) atender
    fila["inicio_atencion"] = f"{time.time():.3f}"
    r = _sh(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            *_env_ciclo(nivel, puerto),
            "api",
            "uv",
            "run",
            "python",
            "-m",
            "scripts.lab_ciclo",
            esc.alertname,
            esc.servicio,
            "--modo",
            modo,
            "--disparada-en",
            f"{disparo:.3f}",
        ],
        timeout=1200,
    )
    m = re.search(r"^RESULTADO (\{.*\})$", r.stdout, re.MULTILINE)
    if not m:
        return fallo(f"el ciclo no termino: {(r.stderr or r.stdout).strip()[-300:]}")
    resultado = json.loads(m.group(1))
    if resultado.get("error"):
        fila["error"] = f"agente: {resultado['error']}"
    # (5) leer el resultado como un operador
    d = _incidente(resultado["incidente"])
    acciones = d.get("acciones") or []
    assert isinstance(acciones, list)
    fila.update(
        incidente=d["id"],
        estado=d["estado"],
        categoria_detectada=d.get("categoria") or "",
        elegible_agente=d.get("elegible"),
        resuelto_autonomo=d.get("resuelto_autonomo"),
        verificado=d.get("verificado"),
        acciones=len(acciones),
        acciones_nombres="|".join(
            f"{a['nombre']}:{'ok' if a['ok'] else 'fallo'}" for a in acciones
        ),
        cerrado_en=d.get("cerrado_en") or "",
        tokens_entrada=d.get("tokens_entrada") or 0,
        tokens_salida=d.get("tokens_salida") or 0,
        turnos_llm=d.get("turnos_llm") or 0,
        llamadas_tools=d.get("llamadas_tools") or 0,
        modelo_llm=d.get("modelo_llm") or "",
        motivo_escalamiento=d.get("motivo_escalamiento") or "",
    )
    if d.get("cerrado_en"):
        fila["mttr_s"] = f"{float(d['cerrado_en']) - disparo:.1f}"  # type: ignore[arg-type]
    print(
        f"  {d['estado']} autonomo={d.get('resuelto_autonomo')} mttr={fila['mttr_s'] or '-'}s"
        f" acciones={fila['acciones_nombres'] or '-'}"
    )
    # (6) recuperar para la proxima corrida (si el agente no lo hizo)
    if esc.recuperar and _prom(esc.anomalia):
        _sh(["sh", f"scripts/fallas/{esc.recuperar}"], reintentos=3)
    return fila


def main() -> int:
    p = argparse.ArgumentParser(description="Experimento de la Fase 7.")
    p.add_argument(
        "--categorias",
        default="servicio_detenido,pod_fallido,disco_lleno,cola_detenida,certificado_por_vencer",
    )
    p.add_argument("--repeticiones", type=int, default=3)
    p.add_argument(
        "--nivel",
        type=int,
        default=3,
        choices=(1, 3, 4),
        help="2 no: con LLM la pausa de aprobacion no reanuda el grafo (ver plan)",
    )
    p.add_argument("--modo", choices=("script", "llm"), default="script")
    p.add_argument("--salida", required=True)
    p.add_argument(
        "--fase",
        choices=("ajuste", "final"),
        default="ajuste",
        help="ajuste: corridas donde se afina el agente. final: el resultado de la tesis "
        "(exige el agente congelado, ver scripts/congelar.py)",
    )
    args = p.parse_args()

    cats = [c.strip() for c in args.categorias.split(",") if c.strip()]
    if desconocidas := [c for c in cats if c not in ESCENARIOS]:
        raise SystemExit(f"Categorias desconocidas: {desconocidas}")
    if _prom("up") is None:
        raise SystemExit(f"Prometheus no responde en {PROMETHEUS}: levantar el laboratorio")
    puerto = _puerto_k8s()

    salida = Path(args.salida)
    salida.parent.mkdir(parents=True, exist_ok=True)
    nuevo = not salida.exists()
    with salida.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS)
        if nuevo:
            w.writeheader()
        for n in range(1, args.repeticiones + 1):
            for cat in cats:  # intercalado: una categoria lenta no concentra sus corridas
                print(f"[{n}/{args.repeticiones}] {cat} (modo {args.modo}, nivel {args.nivel})")
                w.writerow(correr(cat, n, args.modo, args.nivel, puerto, args.fase))
                f.flush()  # una corrida cortada no pierde las anteriores
    print(f"Listo: {salida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
