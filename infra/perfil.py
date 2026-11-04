"""Perfil de ambiente (AIOPS_PERFIL): adapta el agente a otro Grafana + Prometheus + Loki +
Kubernetes sin tocar codigo. Se valida entero al cargar: un perfil invalido o sin aprobar
detiene el arranque en vez de actuar con una configuracion a medias. Sin AIOPS_PERFIL, la
conducta es la de siempre (catalogo y PromQL por defecto). Ver docs/ambientes.md.

El perfil no lleva secretos: URLs y credenciales siguen en el entorno.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from domain.aiops_core.acciones import ACCIONES_PERMITIDAS, validar_servicio
from domain.aiops_core.catalogo import _OPERADORES, CategoriaL1, Senal, activar_catalogo
from domain.aiops_core.modelos import NivelAutonomia, Severidad

_RUNBOOKS = Path(__file__).resolve().parent.parent / "agents" / "aiops" / "runbooks"
_ID = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_ETIQUETA = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_K8S_NOMBRE = re.compile(r"^[a-z0-9]([-a-z0-9.]{0,61}[a-z0-9])?$")


class PerfilInvalido(ValueError):
    pass


@dataclass(frozen=True)
class MapeoWebhook:
    """Rutas con puntos dentro de cada alerta. Por defecto, formato Grafana/Alertmanager."""

    lista: str = "alerts"
    nombre: str = "labels.alertname"
    servicio: str | None = None  # None = labels.<etiqueta_servicio>, y si falta labels.job
    severidad: str = "labels.severity"
    resumen: str = "annotations.summary"
    inicio: str = "startsAt"
    huella: str = "fingerprint"
    estado: str = "status"
    valor_firing: str = "firing"
    severidades: dict[str, Severidad] = field(default_factory=dict)


@dataclass(frozen=True)
class DestinoK8s:
    namespace: str | None = None
    deployment: str | None = None
    selector: str | None = None


@dataclass(frozen=True)
class Kubernetes:
    namespaces: frozenset[str] = frozenset()
    etiqueta_app: str = "app"
    servicios: dict[str, DestinoK8s] = field(default_factory=dict)


@dataclass(frozen=True)
class Perfil:
    entorno: str
    categorias: tuple[CategoriaL1, ...]
    niveles: dict[str, NivelAutonomia]
    consultas: dict[str, str]
    etiqueta_servicio: str = "service"
    etiqueta_logs: str | None = None
    mountpoint: str = "/"
    servicios: frozenset[str] | None = None
    webhook: MapeoWebhook = MapeoWebhook()
    kubernetes: Kubernetes = Kubernetes()


def _dict(valor: Any, donde: str) -> dict[str, Any]:
    if valor is None:
        return {}
    if not isinstance(valor, dict):
        raise PerfilInvalido(f"{donde} debe ser un mapa")
    return valor


def _sin_extras(datos: dict[str, Any], permitidas: set[str], donde: str) -> None:
    # Un typo en una clave de seguridad (`namespace:` por `namespaces:`) no puede pasar callado.
    if extras := set(datos) - permitidas:
        raise PerfilInvalido(f"{donde}: claves desconocidas {sorted(extras)}")


def _etiqueta(valor: Any, donde: str) -> str:
    if not isinstance(valor, str) or not _ETIQUETA.fullmatch(valor):
        raise PerfilInvalido(f"{donde}: etiqueta invalida {valor!r}")
    return valor


def _plantilla(consulta: Any, metrica: str) -> str:
    """El perfil escribe PromQL normal con $servicio, $etiqueta y $mountpoint; el adaptador usa
    str.format, y por eso se escapan las llaves. Exigir $servicio impide una consulta fija que
    "verifique" la salud de otra cosa."""
    if not isinstance(consulta, str) or "$servicio" not in consulta:
        raise PerfilInvalido(f"consulta {metrica!r}: debe ser texto y usar $servicio")
    plantilla = consulta.replace("{", "{{").replace("}", "}}")
    return (
        plantilla.replace("$servicio", "{s}")
        .replace("$etiqueta", "{l}")
        .replace("$mountpoint", "{m}")
    )


def _categoria(c: Any) -> tuple[CategoriaL1, NivelAutonomia]:
    c = _dict(c, "categoria")
    _sin_extras(
        c,
        {"id", "nombre", "alertas", "runbook", "senal", "accion", "rollback", "nivel"},
        f"categoria {c.get('id')!r}",
    )
    cid = c.get("id")
    if not isinstance(cid, str) or not _ID.fullmatch(cid):
        raise PerfilInvalido(f"id de categoria invalido: {cid!r}")
    alertas = c.get("alertas")
    if not isinstance(alertas, list) or not alertas or not all(isinstance(a, str) for a in alertas):
        raise PerfilInvalido(f"{cid}: alertas debe ser una lista de nombres")
    runbook = str(c.get("runbook", ""))
    if not re.fullmatch(r"RB-\d{3}", runbook) or not list(_RUNBOOKS.glob(f"{runbook}-*.md")):
        raise PerfilInvalido(f"{cid}: runbook inexistente {runbook!r}")
    for clave in ("accion", "rollback"):
        if c.get(clave) is not None and c[clave] not in ACCIONES_PERMITIDAS:
            raise PerfilInvalido(f"{cid}: {clave} fuera de la lista autorizada: {c[clave]!r}")
    senal = _dict(c.get("senal"), f"{cid}.senal")
    if senal.get("operador") not in _OPERADORES or not isinstance(senal.get("metrica"), str):
        raise PerfilInvalido(f"{cid}: senal invalida")
    try:
        umbral = float(senal["umbral"])
        nivel = NivelAutonomia(int(c.get("nivel", NivelAutonomia.RECOMIENDA)))
    except (KeyError, TypeError, ValueError) as exc:
        raise PerfilInvalido(f"{cid}: umbral o nivel invalido") from exc
    categoria = CategoriaL1(
        id=cid,
        nombre=str(c.get("nombre") or cid),
        alertas=tuple(alertas),
        runbook_id=runbook,
        senal_sana=Senal(senal["metrica"], senal["operador"], umbral),
        accion=c.get("accion"),
        rollback=c.get("rollback"),
    )
    return categoria, nivel


def _webhook(datos: dict[str, Any]) -> MapeoWebhook:
    _sin_extras(datos, set(MapeoWebhook.__dataclass_fields__), "webhook")
    crudas = _dict(datos.get("severidades"), "webhook.severidades")
    try:
        severidades = {str(k).strip().lower(): Severidad(v) for k, v in crudas.items()}
    except ValueError as exc:
        raise PerfilInvalido(f"webhook.severidades: {exc}") from exc
    return MapeoWebhook(**{**datos, "severidades": severidades})


def _kubernetes(datos: dict[str, Any]) -> Kubernetes:
    _sin_extras(datos, {"namespaces", "etiqueta_app", "servicios"}, "kubernetes")
    namespaces = frozenset(datos.get("namespaces") or ())
    destinos: dict[str, DestinoK8s] = {}
    for servicio, d in _dict(datos.get("servicios"), "kubernetes.servicios").items():
        d = _dict(d, f"kubernetes.servicios.{servicio}")
        _sin_extras(d, {"namespace", "deployment", "selector"}, f"servicio {servicio}")
        for valor in d.values():
            if not _K8S_NOMBRE.fullmatch(str(valor)):
                raise PerfilInvalido(f"servicio {servicio}: nombre invalido {valor!r}")
        destinos[validar_servicio(str(servicio))] = DestinoK8s(**d)
    for n in namespaces:
        if not _K8S_NOMBRE.fullmatch(str(n)):
            raise PerfilInvalido(f"namespace invalido: {n!r}")
    for servicio, destino in destinos.items():
        if destino.namespace and destino.namespace not in namespaces:
            raise PerfilInvalido(
                f"servicio {servicio}: namespace {destino.namespace!r} no permitido"
            )
    return Kubernetes(
        namespaces, _etiqueta(datos.get("etiqueta_app", "app"), "etiqueta_app"), destinos
    )


def parsear(datos: Any) -> Perfil:
    from infra.observabilidad import CONSULTAS_POR_DEFECTO

    datos = _dict(datos, "perfil")
    _sin_extras(
        datos,
        {
            "version", "aprobado", "aprobado_por", "entorno", "observabilidad", "consultas",
            "categorias", "servicios", "webhook", "kubernetes",
        },
        "perfil",
    )  # fmt: skip
    if datos.get("version") != 1:
        raise PerfilInvalido("version debe ser 1")
    # Solo True literal con responsable: un "yes" entre comillas o un borrador no activan nada.
    if datos.get("aprobado") is not True or not str(datos.get("aprobado_por") or "").strip():
        raise PerfilInvalido("perfil sin aprobar: revisarlo y poner aprobado: true y aprobado_por")
    entorno = datos.get("entorno")
    if not isinstance(entorno, str) or not entorno.strip():
        raise PerfilInvalido("falta entorno")
    obs = _dict(datos.get("observabilidad"), "observabilidad")
    _sin_extras(obs, {"etiqueta_servicio", "etiqueta_logs", "mountpoint"}, "observabilidad")
    if '"' in str(obs.get("mountpoint", "")):
        raise PerfilInvalido("mountpoint invalido")
    consultas = {
        str(m): _plantilla(q, str(m)) for m, q in _dict(datos.get("consultas"), "consultas").items()
    }
    pares = [_categoria(c) for c in datos.get("categorias") or []]
    if not pares:
        raise PerfilInvalido("el perfil no define categorias")
    vistos: set[str] = set()
    ids: set[str] = set()
    for categoria, _ in pares:
        if categoria.id in ids:
            raise PerfilInvalido(f"categoria repetida: {categoria.id}")
        ids.add(categoria.id)
        if repetidas := vistos & set(categoria.alertas):
            raise PerfilInvalido(f"alerta en dos categorias: {sorted(repetidas)}")
        vistos |= set(categoria.alertas)
        metrica = categoria.senal_sana.metrica
        if metrica not in consultas and metrica not in CONSULTAS_POR_DEFECTO:
            raise PerfilInvalido(f"{categoria.id}: la senal {metrica!r} no tiene consulta")
    servicios = datos.get("servicios")
    etiqueta_logs = obs.get("etiqueta_logs")
    return Perfil(
        entorno=entorno.strip(),
        categorias=tuple(c for c, _ in pares),
        niveles={c.id: n for c, n in pares},
        consultas=consultas,
        etiqueta_servicio=_etiqueta(obs.get("etiqueta_servicio", "service"), "etiqueta_servicio"),
        etiqueta_logs=_etiqueta(etiqueta_logs, "etiqueta_logs") if etiqueta_logs else None,
        mountpoint=str(obs.get("mountpoint", "/")),
        servicios=frozenset(validar_servicio(str(s)) for s in servicios) if servicios else None,
        webhook=_webhook(_dict(datos.get("webhook"), "webhook")),
        kubernetes=_kubernetes(_dict(datos.get("kubernetes"), "kubernetes")),
    )


def cargar(ruta: str | Path) -> Perfil:
    try:
        datos = yaml.safe_load(Path(ruta).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise PerfilInvalido(f"no se pudo leer el perfil {ruta}: {exc}") from exc
    return parsear(datos)


@lru_cache(maxsize=4)
def _cargar_y_activar(ruta: str) -> Perfil:
    perfil = cargar(ruta)
    activar_catalogo(perfil.categorias)
    return perfil


def activo() -> Perfil | None:
    """El perfil de AIOPS_PERFIL ya aplicado al catalogo del proceso, o None si no hay."""
    ruta = os.environ.get("AIOPS_PERFIL", "").strip()
    return _cargar_y_activar(ruta) if ruta else None
