"""Catalogo de categorias L1 elegibles para automatizacion.

Son candidatos de diseño (ver tesis, "Casos L1 candidatos"): hay que validarlos
contra frecuencia, impacto y runbooks reales antes de usarlos fuera del banco
experimental. Una categoria sin `accion` es de solo deteccion y escalamiento.
"""

from __future__ import annotations

import operator
from collections.abc import Callable, Iterable
from dataclasses import dataclass

_OPERADORES: dict[str, Callable[[float, float], bool]] = {
    "<=": operator.le,
    ">=": operator.ge,
    "<": operator.lt,
    ">": operator.gt,
}


@dataclass(frozen=True)
class Senal:
    """Criterio de estado sano: `metrica operador umbral`. Si no se cumple hay anomalia;
    si se cumple tras la accion, hay recuperacion comprobable."""

    metrica: str
    operador: str
    umbral: float

    def cumple(self, valor: float) -> bool:
        return _OPERADORES[self.operador](valor, self.umbral)

    def describir(self) -> str:
        return f"{self.metrica} {self.operador} {self.umbral:g}"


@dataclass(frozen=True)
class CategoriaL1:
    id: str
    nombre: str
    alertas: tuple[str, ...]  # nombres de alerta (alertname) que mapean a esta categoria
    runbook_id: str
    senal_sana: Senal
    accion: str | None = None  # accion autorizada de remediacion; None = solo escalar
    rollback: str | None = None

    @property
    def remediable(self) -> bool:
        return self.accion is not None


CATALOGO: dict[str, CategoriaL1] = {
    c.id: c
    for c in (
        CategoriaL1(
            id="servicio_detenido",
            nombre="Servicio detenido",
            alertas=("ServiceDown",),
            runbook_id="RB-001",
            senal_sana=Senal("up", ">=", 1),
            accion="restart_service",
        ),
        CategoriaL1(
            id="disco_lleno",
            nombre="Uso anomalo de disco",
            alertas=("DiskUsageHigh",),
            runbook_id="RB-002",
            senal_sana=Senal("disk_usage_percent", "<=", 85),
            accion="compress_old_logs",
            rollback="restore_compressed_logs",
        ),
        CategoriaL1(
            id="pod_fallido",
            nombre="Pod en estado fallido",
            alertas=("PodCrashLooping", "PodFailed"),
            runbook_id="RB-003",
            senal_sana=Senal("pod_ready", ">=", 1),
            accion="recreate_pod",
        ),
        CategoriaL1(
            id="cola_detenida",
            nombre="Cola de trabajo detenida",
            alertas=("QueueStalled",),
            runbook_id="RB-004",
            senal_sana=Senal("queue_consumers_active", ">=", 1),
            accion="restart_consumer",
        ),
        CategoriaL1(
            id="certificado_por_vencer",
            nombre="Certificado proximo a vencer",
            alertas=("CertExpiringSoon",),
            runbook_id="RB-005",
            senal_sana=Senal("cert_days_remaining", ">=", 14),
            accion=None,  # solo deteccion y escalamiento
        ),
    )
}


_POR_DEFECTO = tuple(CATALOGO.values())


def activar_catalogo(categorias: Iterable[CategoriaL1]) -> None:
    """Reemplaza el catalogo del proceso (perfil de ambiente). Se muta en el lugar porque hay
    modulos que importaron `CATALOGO`."""
    nuevas = {c.id: c for c in categorias}
    CATALOGO.clear()
    CATALOGO.update(nuevas)


def restaurar_catalogo() -> None:
    activar_catalogo(_POR_DEFECTO)


def categoria_para_alerta(nombre_alerta: str) -> CategoriaL1 | None:
    for categoria in CATALOGO.values():
        if nombre_alerta in categoria.alertas:
            return categoria
    return None
