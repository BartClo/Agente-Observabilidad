"""`BackendAcciones` para Docker Compose SIN docker.sock (ADR-003).

El agente no toca Docker: deja una solicitud en un directorio compartido con el host y
espera la respuesta. Quien ejecuta es `deploy/aifactory/ejecutor/aiops_ejecutor.py`, una
unidad systemd del host con su propia lista de servicios permitidos y su limite de
reinicios. Si el contenedor del agente se compromete, lo maximo que puede hacer es PEDIR
un reinicio de un servicio que el host ya autorizo.

    <dir>/pendientes/<id>.json   lo escribe el agente: {"id", "accion", "servicio", "ts"}
    <dir>/resultados/<id>.json   lo escribe el ejecutor: {"ok": bool, "detalle": str}
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path


class BackendSolicitudes:
    def __init__(self, directorio: str | Path, intervalo_s: float = 0.5) -> None:
        self._pend = Path(directorio) / "pendientes"
        self._res = Path(directorio) / "resultados"
        self._intervalo = intervalo_s

    @classmethod
    def desde_entorno(cls) -> BackendSolicitudes:
        return cls(os.environ.get("AIOPS_SOLICITUDES_DIR", "/solicitudes"))

    def ejecutar(self, accion: str, servicio: str, timeout_s: int) -> str:
        """`accion` y `servicio` ya llegan validados por ejecutar_accion (lista autorizada y
        nombre seguro). El ejecutor del host los vuelve a validar: no confia en el agente."""
        self._pend.mkdir(parents=True, exist_ok=True)
        id_ = uuid.uuid4().hex
        pedido = {"id": id_, "accion": accion, "servicio": servicio, "ts": time.time()}
        tmp = self._pend / f".{id_}.tmp"
        tmp.write_text(json.dumps(pedido), encoding="utf-8")
        tmp.replace(self._pend / f"{id_}.json")  # atomico: el ejecutor nunca lee a medias
        respuesta = self._res / f"{id_}.json"
        # Un poco antes del limite de ejecutar_accion, para alcanzar a retirar el pedido.
        limite = time.monotonic() + max(1.0, timeout_s - 5)
        while time.monotonic() < limite:
            if respuesta.exists():
                datos = json.loads(respuesta.read_text(encoding="utf-8"))
                respuesta.unlink(missing_ok=True)
                if datos.get("ok") is True:
                    return str(datos.get("detalle", "ok"))
                raise RuntimeError(f"el ejecutor del host rechazo o fallo: {datos.get('detalle')}")
            time.sleep(self._intervalo)
        # Sin respuesta: se retira el pedido para que no se ejecute tarde. Si el ejecutor ya
        # lo tomo, el resultado es incierto y el agente verifica en vez de reintentar.
        (self._pend / f"{id_}.json").unlink(missing_ok=True)
        raise TimeoutError(
            f"el ejecutor del host no respondio en {timeout_s}s ({accion} {servicio})"
        )
