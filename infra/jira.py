"""Cliente minimo de Jira Cloud (solo stdlib, igual que infra/acciones_k8s.py).

Lee tableros, columnas y tickets (API Agile 1.0) y escribe solo dos cosas: un comentario y una
transicion a un estado que configuro el administrador (API REST 2). No crea tickets ni edita
campos. La JQL se arma aca con ids de estado numericos validados: nunca llega texto libre.
"""

from __future__ import annotations

import base64
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from infra.jira_config import Columna

CLAVE = re.compile(r"^[A-Z][A-Z0-9_]{0,30}-[0-9]{1,9}$")
_ESTADO = re.compile(r"^[0-9]{1,10}$")
_CAMPOS = "summary,description,labels,priority,created"


class ErrorJira(RuntimeError):
    """Jira respondio con error o no respondio. El mensaje nunca incluye credenciales."""


@dataclass(frozen=True)
class Ticket:
    clave: str
    titulo: str
    descripcion: str
    etiquetas: tuple[str, ...]
    prioridad: str
    creado: float | None


def _texto_adf(nodo: Any) -> str:
    """La API devuelve la descripcion como texto o como documento ADF (Cloud)."""
    if isinstance(nodo, str):
        return nodo
    if isinstance(nodo, dict):
        if nodo.get("type") == "text":
            return str(nodo.get("text", ""))
        return "".join(_texto_adf(h) for h in nodo.get("content", []))
    if isinstance(nodo, list):
        return "".join(_texto_adf(h) for h in nodo)
    return ""


def _fecha(valor: Any) -> float | None:
    try:
        return datetime.strptime(str(valor), "%Y-%m-%dT%H:%M:%S.%f%z").timestamp()
    except ValueError:
        return None


def _clave(clave: str) -> str:
    if not CLAVE.fullmatch(clave):
        raise ErrorJira(f"clave de ticket invalida: {clave[:40]!r}")
    return clave


class ClienteJira:
    def __init__(self, sitio: str, correo: str, token: str, timeout_s: int = 10) -> None:
        self._sitio = sitio.rstrip("/")
        credencial = base64.b64encode(f"{correo}:{token}".encode()).decode()
        self._auth = f"Basic {credencial}"
        self._timeout = timeout_s

    def _pedir(self, metodo: str, ruta: str, cuerpo: Any = None) -> Any:
        datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
        req = urllib.request.Request(  # noqa: S310  (sitio validado en infra/jira_config.py)
            f"{self._sitio}{ruta}",
            data=datos,
            method=metodo,
            headers={
                "Authorization": self._auth,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        donde = f"{metodo} {ruta.split('?')[0]}"
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:  # noqa: S310
                cuerpo_resp = resp.read().decode()
        except urllib.error.HTTPError as exc:
            raise ErrorJira(f"Jira respondio {exc.code} en {donde}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ErrorJira(f"Jira no responde en {donde}: {type(exc).__name__}") from None
        return json.loads(cuerpo_resp) if cuerpo_resp else {}

    def yo(self) -> str:
        return str(self._pedir("GET", "/rest/api/2/myself").get("displayName", "?"))

    def tableros(self) -> list[dict[str, Any]]:
        datos = self._pedir("GET", "/rest/agile/1.0/board?maxResults=50")
        return [{"id": int(b["id"]), "nombre": str(b["name"])} for b in datos.get("values", [])]

    def columnas(self, tablero_id: int) -> list[Columna]:
        datos = self._pedir("GET", f"/rest/agile/1.0/board/{int(tablero_id)}/configuration")
        return [
            Columna(str(c["name"]), tuple(str(s["id"]) for s in c.get("statuses", [])))
            for c in datos.get("columnConfig", {}).get("columns", [])
        ]

    def tickets(self, tablero_id: int, estados: tuple[str, ...], maximo: int) -> list[Ticket]:
        if not estados or not all(_ESTADO.fullmatch(e) for e in estados):
            raise ErrorJira("estado invalido para la JQL")
        consulta = urllib.parse.urlencode(
            {
                "jql": f"status in ({','.join(estados)}) ORDER BY created ASC",
                "fields": _CAMPOS,
                "maxResults": max(1, min(maximo, 50)),
            }
        )
        datos = self._pedir("GET", f"/rest/agile/1.0/board/{int(tablero_id)}/issue?{consulta}")
        salida = []
        for i in datos.get("issues", []):
            if not CLAVE.fullmatch(str(i.get("key", ""))):
                continue
            f = i.get("fields", {})
            salida.append(
                Ticket(
                    clave=i["key"],
                    titulo=str(f.get("summary") or ""),
                    descripcion=_texto_adf(f.get("description")),
                    etiquetas=tuple(str(e) for e in f.get("labels") or []),
                    prioridad=str((f.get("priority") or {}).get("name") or ""),
                    creado=_fecha(f.get("created")),
                )
            )
        return salida

    def comentar(self, clave: str, texto: str) -> None:
        self._pedir("POST", f"/rest/api/2/issue/{_clave(clave)}/comment", {"body": texto})

    def transicionar(self, clave: str, estados: tuple[str, ...]) -> bool:
        """Aplica la primera transicion cuyo destino es uno de `estados`. False si no hay."""
        ruta = f"/rest/api/2/issue/{_clave(clave)}/transitions"
        for t in self._pedir("GET", ruta).get("transitions", []):
            if str((t.get("to") or {}).get("id")) in estados:
                self._pedir("POST", ruta, {"transition": {"id": str(t["id"])}})
                return True
        return False
