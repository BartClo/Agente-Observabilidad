"""Entorno simulado: banco experimental reproducible con inyeccion de fallos.

Implementa `ObservabilidadPort` y `BackendAcciones`. Sirve para tests, evals y demos
sin tocar infraestructura real (la tesis lo plantea como alternativa acotada a AIOpsLab).
"""

from __future__ import annotations

from domain.aiops_core.catalogo import CATALOGO, categoria_para_alerta
from domain.aiops_core.modelos import Alerta, Severidad

_SANO = {
    "up": 1.0,
    "disk_usage_percent": 40.0,
    "pod_ready": 1.0,
    "queue_consumers_active": 2.0,
    "cert_days_remaining": 90.0,
}
_FALLA = {
    "servicio_detenido": ("up", 0.0),
    "disco_lleno": ("disk_usage_percent", 96.0),
    "pod_fallido": ("pod_ready", 0.0),
    "cola_detenida": ("queue_consumers_active", 0.0),
    "certificado_por_vencer": ("cert_days_remaining", 3.0),
}
# accion -> (metrica, valor tras la accion)
_EFECTO = {
    "restart_service": ("up", 1.0),
    "compress_old_logs": ("disk_usage_percent", 60.0),
    "restore_compressed_logs": ("disk_usage_percent", 96.0),
    "recreate_pod": ("pod_ready", 1.0),
    "restart_consumer": ("queue_consumers_active", 2.0),
}


class EntornoSimulado:
    def __init__(self, entorno: str = "staging") -> None:
        self.entorno = entorno
        self.acciones_efectivas = True  # False: la accion "funciona" pero no recupera
        self.acciones_ejecutadas: list[tuple[str, str]] = []
        self._metricas: dict[str, dict[str, float]] = {}
        self._alertas: list[Alerta] = []

    def inyectar_fallo(
        self, servicio: str, categoria_id: str, severidad: Severidad = Severidad.MEDIA
    ) -> Alerta:
        metrica, valor = _FALLA[categoria_id]
        self._metricas.setdefault(servicio, {})[metrica] = valor
        alerta = Alerta(
            id=f"A{len(self._alertas) + 1}",
            nombre=CATALOGO[categoria_id].alertas[0],
            servicio=servicio,
            entorno=self.entorno,
            severidad=severidad,
            resumen=f"{CATALOGO[categoria_id].nombre} en {servicio} (simulado)",
        )
        self._alertas.append(alerta)
        return alerta

    # --- ObservabilidadPort ---------------------------------------------------------

    def alertas_activas(self) -> list[Alerta]:
        activas = []
        for a in self._alertas:
            categoria = categoria_para_alerta(a.nombre)
            valor = self.metrica(a.servicio, categoria.senal_sana.metrica) if categoria else None
            if categoria is None or valor is None or not categoria.senal_sana.cumple(valor):
                activas.append(a)
        return activas

    def metrica(self, servicio: str, nombre: str) -> float | None:
        if nombre not in _SANO:
            return None
        return self._metricas.get(servicio, {}).get(nombre, _SANO[nombre])

    def logs(self, servicio: str, lineas: int, desde: float | None = None) -> list[str]:
        estado = ", ".join(f"{k}={v:g}" for k, v in self._metricas.get(servicio, {}).items())
        return [f"{servicio}: estado simulado [{estado or 'sano'}]"][:lineas]

    # --- InvestigacionPort ----------------------------------------------------------

    def eventos(self, servicio: str, maximo: int) -> list[str]:
        listo = self._metricas.get(servicio, {}).get("pod_ready", _SANO["pod_ready"])
        return [f"pod {servicio}-sim: listo={'si' if listo else 'no'} (simulado)"][:maximo]

    # --- BackendAcciones ------------------------------------------------------------

    def ejecutar(self, accion: str, servicio: str, timeout_s: int) -> str:
        self.acciones_ejecutadas.append((accion, servicio))
        if self.acciones_efectivas:
            metrica, valor = _EFECTO[accion]
            self._metricas.setdefault(servicio, {})[metrica] = valor
        return f"{accion} aplicado sobre {servicio} (simulado)"
