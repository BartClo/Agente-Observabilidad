#!/usr/bin/env python3
"""Ejecutor de acciones del agente AIOps en el HOST (ADR-003). Solo stdlib.

Lee las solicitudes que el agente deja en <dir>/pendientes, las valida con reglas
PROPIAS (no confia en el agente) y ejecuta `docker restart`. Corre como unidad systemd
con un usuario del grupo docker; el contenedor del agente nunca toca docker.sock.

Reglas:
- accion: restart_service o restart_consumer (las dos son `docker restart`).
- servicio: nombre seguro y presente en el archivo de permitidos (se relee en cada
  solicitud: editarlo aplica sin reiniciar el ejecutor).
- limite: como maximo MAX_POR_HORA reinicios por servicio en la ultima hora.
- solicitudes con mas de VENCE_S segundos se descartan (el agente ya dejo de esperar).

    AIOPS_SOLICITUDES_DIR=/var/lib/aiops/solicitudes \
    AIOPS_EJECUTOR_PERMITIDOS=/etc/aiops/servicios-permitidos \
    python3 aiops_ejecutor.py
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path

ACCIONES = {"restart_service", "restart_consumer"}
LECTURA = {"inspeccionar"}  # solo lectura: sin limite por hora
NOMBRE = re.compile(r"^[A-Za-z0-9_.-]{1,63}$")
ID = re.compile(r"^[0-9a-f]{32}$")

log = logging.getLogger("aiops-ejecutor")


class Ejecutor:
    def __init__(
        self,
        directorio: Path,
        permitidos: Path,
        prefijo: str = "ia-factory-",
        max_por_hora: int = 3,
        vence_s: float = 120,
        correr: Callable[[list[str]], subprocess.CompletedProcess[str]] | None = None,
    ) -> None:
        self.pend, self.res = directorio / "pendientes", directorio / "resultados"
        self.permitidos, self.prefijo = permitidos, prefijo
        self.max_por_hora, self.vence_s = max_por_hora, vence_s
        self._correr = correr or (
            lambda cmd: subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        )
        # ponytail: el historial vive en memoria; reiniciar el ejecutor lo vacia. Persistirlo
        # si el limite tiene que sobrevivir reinicios del host.
        self._historial: dict[str, list[float]] = defaultdict(list)

    def _servicios_permitidos(self) -> set[str]:
        try:
            lineas = self.permitidos.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return set()
        return {s.strip() for s in lineas if s.strip() and not s.strip().startswith("#")}

    def decidir(self, pedido: dict[str, object], ahora: float) -> tuple[bool, str]:
        accion, servicio = pedido.get("accion"), pedido.get("servicio")
        if accion not in ACCIONES | LECTURA:
            return False, f"accion no permitida en el host: {accion!r}"
        if not isinstance(servicio, str) or not NOMBRE.fullmatch(servicio):
            return False, "nombre de servicio invalido"
        if servicio not in self._servicios_permitidos():
            return False, f"{servicio} no esta en la lista de servicios permitidos del host"
        ts = pedido.get("ts")
        if not isinstance(ts, (int, float)) or ahora - ts > self.vence_s:
            return False, "solicitud vencida"
        if accion in LECTURA:
            return self._inspeccionar(self.prefijo + servicio)
        recientes = [t for t in self._historial[servicio] if ahora - t < 3600]
        self._historial[servicio] = recientes
        if len(recientes) >= self.max_por_hora:
            return False, f"limite: {len(recientes)} reinicios de {servicio} en la ultima hora"
        contenedor = self.prefijo + servicio
        r = self._correr(["docker", "restart", "--time", "30", contenedor])
        if r.returncode != 0:
            return (
                False,
                f"docker restart {contenedor} fallo: {(r.stderr or r.stdout).strip()[:300]}",
            )
        self._historial[servicio].append(ahora)
        return True, f"docker restart {contenedor}: ok"

    def _inspeccionar(self, contenedor: str) -> tuple[bool, str]:
        r = self._correr(["docker", "inspect", contenedor])
        if r.returncode != 0:
            return (
                False,
                f"docker inspect {contenedor} fallo: {(r.stderr or r.stdout).strip()[:300]}",
            )
        try:
            datos = json.loads(r.stdout)[0]
        except (ValueError, IndexError, KeyError) as exc:
            return False, f"docker inspect ilegible: {exc}"
        e = datos.get("State", {})
        salud = e.get("Health") or {}
        lineas = [
            f"estado={e.get('Status')} codigo_salida={e.get('ExitCode')} "
            f"oom={e.get('OOMKilled')} reinicios={datos.get('RestartCount')}",
            f"iniciado={e.get('StartedAt')} terminado={e.get('FinishedAt')}",
        ]
        if e.get("Error"):
            lineas.append(f"error={e['Error'][:200]}")
        if salud:
            ultimo = (salud.get("Log") or [{}])[-1]
            lineas.append(
                f"healthcheck={salud.get('Status')} fallos_seguidos={salud.get('FailingStreak')} "
                f"ultimo={str(ultimo.get('Output', '')).strip()[:200]}"
            )
        return True, "\n".join(lineas)

    def procesar_pendientes(self, ahora: float | None = None) -> int:
        self.res.mkdir(parents=True, exist_ok=True)
        hechos = 0
        for archivo in sorted(self.pend.glob("*.json")):
            id_ = archivo.stem
            try:
                pedido = json.loads(archivo.read_text(encoding="utf-8"))
                archivo.unlink()  # se toma una sola vez, pase lo que pase
            except (OSError, ValueError) as exc:
                log.warning("solicitud ilegible %s: %s", archivo.name, exc)
                archivo.unlink(missing_ok=True)
                continue
            if not ID.fullmatch(id_) or not isinstance(pedido, dict):
                log.warning("solicitud con id invalido: %s", archivo.name)
                continue
            ok, detalle = self.decidir(pedido, time.time() if ahora is None else ahora)
            log.info(
                "%s %s %s -> %s: %s", id_, pedido.get("accion"), pedido.get("servicio"), ok, detalle
            )
            tmp = self.res / f".{id_}.tmp"
            tmp.write_text(json.dumps({"ok": ok, "detalle": detalle}), encoding="utf-8")
            tmp.replace(self.res / f"{id_}.json")
            hechos += 1
        return hechos


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    e = Ejecutor(
        Path(os.environ.get("AIOPS_SOLICITUDES_DIR", "/var/lib/aiops/solicitudes")),
        Path(os.environ.get("AIOPS_EJECUTOR_PERMITIDOS", "/etc/aiops/servicios-permitidos")),
        prefijo=os.environ.get("AIOPS_EJECUTOR_PREFIJO", "ia-factory-"),
        max_por_hora=int(os.environ.get("AIOPS_EJECUTOR_MAX_POR_HORA", "3")),
    )
    e.pend.mkdir(parents=True, exist_ok=True)
    log.info("escuchando %s (permitidos: %s)", e.pend, sorted(e._servicios_permitidos()))
    while True:
        try:
            e.procesar_pendientes()
        except Exception:
            log.exception("error procesando solicitudes")
        time.sleep(1)


if __name__ == "__main__":
    main()
