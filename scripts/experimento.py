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
from collections.abc import Iterator, Sequence
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parent.parent
PROMETHEUS = os.environ.get("EXP_PROMETHEUS", "http://localhost:9090")
API = os.environ.get("EXP_API", "http://localhost:8010")
GRAFANA = os.environ.get("EXP_GRAFANA", "http://localhost:3001")


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
    # Consumidor SIMULADO en k3d (k8s-lab/workload-queue-consumer.yaml): restart_consumer
    # lo arregla de verdad, como a checkout. No es un RabbitMQ real: se declara en la tesis.
    "cola_detenida": Escenario(
        "QueueStalled",
        "worker",
        "cola_detenida.sh",
        'max(rabbitmq_queue_consumers{queue="worker"}) < 1',
        "recuperar_cola.sh",
        usa_k8s=True,
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
    "rag",
    "via",
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
    "deteccion_s",
    "cerrado_en",
    "mttr_s",
    "tokens_entrada",
    "tokens_salida",
    "turnos_llm",
    "llamadas_tools",
    "modelo_llm",
    "confianza",
    "fuentes_recuperadas",
    "fuentes_citadas",
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


# Aislamiento entre corridas: cada una inyecta una falla en el MISMO servicio, asi que sin
# esto una corrida contamina a la siguiente. (1) El cortacircuito (que existe para frenar la
# recurrencia real) contaria las inyecciones del experimento como recurrencia y escalaria
# artificialmente. (2) Los logs FATAL de la corrida anterior le harian ver al agente
# "reinicios que vuelven a caer". Se desactiva el primero y se acota el segundo a 60 s antes
# de la alerta. Ambos se declaran en la tesis y quedan en resultados/congelado.json.
AISLAMIENTO = {
    "AIOPS_BREAKER_MAX": "0",
    "AIOPS_LOGS_VENTANA_S": "60",
    # Los PDF que un administrador sube desde la UI no entran en lo medido: solo el corpus
    # versionado y auditable (corpus/ + runbooks), cuyo hash queda en congelado.json.
    "AIOPS_RAG_ORIGENES": "repo",
    # Los tickets de Jira no entran en lo medido: el poller no corre en las corridas.
    "AIOPS_JIRA": "0",
}

# RAG durante el experimento. min_sim sale de la calibracion (python -m rag.cli calibrar;
# debe coincidir con agents.aiops.conocimiento.MIN_SIM_DEFECTO) y queda en congelado.json.
# RAG="0" (--sin-rag) es el brazo de comparacion.
CONFIG_RAG = {"AIOPS_RAG_K": "3", "AIOPS_RAG_MIN_SIM": "0.69"}
RAG = "1"


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
        **AISLAMIENTO,
        **CONFIG_RAG,
        "AIOPS_RAG": RAG,
    }
    return [a for k, v in env.items() for a in ("-e", f"{k}={v}")]


TERMINALES = ("resuelto", "escalado", "descartado")


def _listar_incidentes() -> list[dict[str, object]]:
    req = urllib.request.Request(  # noqa: S310
        f"{API}/incidentes", headers={"Authorization": f"Bearer {_token_api()}"}
    )
    with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310
        return [dict(i) for i in json.load(r)]


def buscar_incidente_nuevo(
    lista: Sequence[dict[str, object]], esc: Escenario, desde: float
) -> dict[str, object] | None:
    """El incidente que abrio el worker para la alerta de este escenario despues de `desde`
    (el primero, si hubo mas de uno)."""
    candidatos = [
        i
        for i in lista
        if i.get("alerta") == esc.alertname
        and i.get("servicio") == esc.servicio
        and float(str(i.get("abierto_en") or 0)) >= desde
    ]
    return min(candidatos, key=lambda i: float(str(i["abierto_en"]))) if candidatos else None


def _alerta_en_alerting(alertname: str) -> bool | None:
    """True si la regla de Grafana esta disparada o pendiente; False si esta en Normal;
    None si Grafana no responde o la regla no existe."""
    try:
        with urllib.request.urlopen(  # noqa: S310
            f"{GRAFANA}/api/prometheus/grafana/api/v1/rules", timeout=10
        ) as r:
            grupos = json.load(r)["data"]["groups"]
    except Exception:
        return None
    for grupo in grupos:
        for regla in grupo["rules"]:
            if regla["name"] == alertname:
                return bool(regla["state"] != "inactive")
    return None


def esperar_alerta_inactiva(alertname: str, timeout_s: float = 120.0) -> bool:
    """Camino real: Grafana solo notifica en la TRANSICION a Alerting. Si se vuelve a inyectar
    antes de que vea la alerta en Normal (pod_fallido se recupera en segundos y la regla
    evalua cada 10 s), no hay transicion, no hay webhook y el incidente nunca se abre."""
    limite = time.time() + timeout_s
    while time.time() < limite:
        if _alerta_en_alerting(alertname) is False:
            return True
        time.sleep(3)
    return False


def _esperar_costo(incidente_id: str, espera_s: float) -> None:
    """El worker registra el costo (tokens, turnos, modelo) DESPUES de cerrar o escalar: leer
    el incidente apenas es terminal da turnos=0 y tokens=0 (visto en una corrida real, donde
    7 turnos aparecian como 0). Espera a que `modelo_llm` este registrado."""
    limite = time.time() + espera_s
    while time.time() < limite:
        if _incidente(incidente_id).get("modelo_llm"):
            return
        time.sleep(2)


def esperar_camino_real(
    esc: Escenario,
    disparo: float,
    espera_apertura_s: float = 120.0,
    espera_cierre_s: float = 900.0,
    espera_costo_s: float = 60.0,
) -> tuple[str | None, str]:
    """Camino real: Grafana dispara la alerta, el webhook encola y el worker atiende. Espera
    a que se abra el incidente y a que llegue a un estado terminal. Devuelve (id, "") o un
    motivo: `infra:` si nadie abrio el incidente (no es una decision del agente y el analisis
    lo excluye), `agente:` si se abrio pero no termino (si cuenta)."""
    limite = time.time() + espera_apertura_s
    incidente_id: str | None = None
    while time.time() < limite:
        encontrado = buscar_incidente_nuevo(_listar_incidentes(), esc, disparo - 2)
        if encontrado is not None:
            incidente_id = str(encontrado["id"])
            break
        time.sleep(3)
    if incidente_id is None:
        return None, (
            f"infra: en {espera_apertura_s:.0f} s Grafana no disparo la alerta o el worker no "
            "abrio el incidente"
        )
    limite = time.time() + espera_cierre_s
    while time.time() < limite:
        if _incidente(incidente_id)["estado"] in TERMINALES:
            _esperar_costo(incidente_id, espera_costo_s)
            return incidente_id, ""
        time.sleep(5)
    return incidente_id, (
        f"agente: el incidente no llego a un estado terminal en {espera_cierre_s:.0f} s"
    )


@contextmanager
def worker_de_laboratorio(nivel: int, puerto: str) -> Iterator[None]:
    """Camino real: atiende el worker, no `scripts.lab_ciclo`. El worker del compose no trae
    el entorno del laboratorio (Prometheus, Kubernetes, nivel de autonomia), asi que se baja
    ese y se levanta uno con el MISMO entorno que usa el modo directo. Al terminar se
    restaura el worker normal."""
    nombre = "aiops-worker-lab"
    _sh(["docker", "compose", "stop", "worker"])
    _sh(["docker", "rm", "-f", nombre])
    r = _sh(
        ["docker", "compose", "run", "-d", "--name", nombre, *_env_ciclo(nivel, puerto), "worker"]
    )
    if r.returncode != 0:
        _sh(["docker", "compose", "start", "worker"])
        raise SystemExit(
            f"No se pudo levantar el worker del laboratorio: {r.stderr.strip()[-300:]}"
        )
    try:
        yield
    finally:
        _sh(["docker", "rm", "-f", nombre])
        _sh(["docker", "compose", "start", "worker"])


def _unir(ids: object) -> str:
    """Lista de ids de fuentes (C12, C13) como una sola celda del CSV."""
    return "|".join(str(i) for i in ids) if isinstance(ids, list) else ""


def correr(
    cat: str,
    n: int,
    modo: str,
    nivel: int,
    puerto: str,
    fase: str = "ajuste",
    via: str = "directo",
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
        rag=RAG,
        via=via,
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
    if via == "webhook" and not esperar_alerta_inactiva(esc.alertname):
        return fallo("infra: la alerta de Grafana no volvio a Normal antes de la corrida")
    # (2) inyectar y (3) esperar la anomalia
    r = _sh(["sh", f"scripts/fallas/{esc.falla}"], reintentos=3)
    if r.returncode != 0:
        return fallo(f"infra: no se pudo inyectar la falla: {r.stderr.strip()[-200:]}")
    if not _esperar(esc.anomalia, 180):
        return fallo("infra: la falla no se manifesto en Prometheus")
    disparo = time.time()
    fila["disparada_en"] = f"{disparo:.3f}"
    # (4) atender
    if via == "webhook":
        # camino real: Grafana dispara la alerta, el webhook encola y el worker atiende
        incidente_id, motivo = esperar_camino_real(esc, disparo)
        if incidente_id is None:
            if esc.recuperar:  # no dejar la falla puesta para la corrida siguiente
                _sh(["sh", f"scripts/fallas/{esc.recuperar}"], reintentos=3)
            return fallo(motivo)
        if motivo:
            fila["error"] = motivo
        resultado: dict[str, Any] = {"incidente": incidente_id}
    else:
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
        confianza=d.get("confianza") if d.get("confianza") is not None else "",
        fuentes_recuperadas=_unir(d.get("fuentes_recuperadas")),
        fuentes_citadas=_unir(d.get("fuentes_citadas")),
        motivo_escalamiento=d.get("motivo_escalamiento") or "",
    )
    if via == "webhook":
        fila["inicio_atencion"] = f"{float(str(d['abierto_en'])):.3f}"
        fila["deteccion_s"] = f"{float(str(d['abierto_en'])) - disparo:.1f}"
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


def _git_salida(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=RAIZ, capture_output=True, text=True, check=True
    ).stdout.strip()


def exigir_congelado() -> None:
    """`--fase final` solo corre sobre el agente congelado (scripts/congelar.py): cambiar el
    prompt, el modelo o el codigo a mitad del experimento invalida la comparacion."""
    ruta = RAIZ / "resultados" / "congelado.json"
    if not ruta.exists():
        raise SystemExit("Falta resultados/congelado.json: correr python -m scripts.congelar")
    registro = json.loads(ruta.read_text(encoding="utf-8"))
    actual = _git_salida("rev-parse", "HEAD")
    if registro["commit"] != actual:
        raise SystemExit(
            f"HEAD {actual[:8]} != congelado {str(registro['commit'])[:8]}: el codigo cambio "
            "despues de congelar. Volver al commit congelado o congelar de nuevo y repetir"
        )
    if _git_salida("status", "--porcelain", "--untracked-files=no"):
        raise SystemExit("Hay cambios sin commitear: el agente ya no es el congelado")


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
    p.add_argument(
        "--inyeccion",
        action="store_true",
        help="escenario de seguridad: servicio_detenido con una linea de log hostil. Usar un "
        "CSV aparte (resultados/inyeccion-*.csv): no se mezcla con la TRA",
    )
    p.add_argument(
        "--via",
        choices=("directo", "webhook"),
        default="directo",
        help="directo: invoca el ciclo (rapido, para ajustar). webhook: camino real, espera a "
        "que Grafana dispare la alerta y al worker (mide la deteccion; solo --modo llm)",
    )
    p.add_argument(
        "--sin-rag",
        action="store_true",
        help="brazo de comparacion: el agente no tiene buscar_conocimiento (AIOPS_RAG=0)",
    )
    args = p.parse_args()
    global RAG
    RAG = "0" if args.sin_rag else "1"
    if args.fase == "final":
        exigir_congelado()

    cats = [c.strip() for c in args.categorias.split(",") if c.strip()]
    if desconocidas := [c for c in cats if c not in ESCENARIOS]:
        raise SystemExit(f"Categorias desconocidas: {desconocidas}")
    if args.inyeccion:
        if cats != ["servicio_detenido"]:
            raise SystemExit("--inyeccion solo aplica a --categorias servicio_detenido")
        _ENV_SUB["INYECTAR_LOG"] = "1"
    if args.via == "webhook" and args.modo != "llm":
        raise SystemExit("--via webhook solo con --modo llm: el modo script invoca el ciclo")
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
        contexto = (
            worker_de_laboratorio(args.nivel, puerto) if args.via == "webhook" else nullcontext()
        )
        with contexto:
            for n in range(1, args.repeticiones + 1):
                for cat in cats:  # intercalado: una categoria lenta no concentra sus corridas
                    print(
                        f"[{n}/{args.repeticiones}] {cat} "
                        f"(modo {args.modo}, nivel {args.nivel}, via {args.via})"
                    )
                    w.writerow(correr(cat, n, args.modo, args.nivel, puerto, args.fase, args.via))
                    f.flush()  # una corrida cortada no pierde las anteriores
    print(f"Listo: {salida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
