"""`BackendAcciones` sobre la API de Kubernetes (Fase 4, ver docs/plan-aiops.md).

Solo HTTP (stdlib, sin dependencias nuevas, igual que infra/observabilidad.py). Usa el
token de un ServiceAccount con RBAC minimo (k8s-lab/rbac-aiops.yaml): borrar pods y
parchear deployments, solo en un namespace. El namespace lo fija la configuracion, no
el LLM; el servicio ya llega validado por domain.aiops_core.acciones.ejecutar_accion.

Mapeo de acciones del catalogo:
- recreate_pod: borra los pods `app=<servicio>`; su controlador los repone.
- restart_service / restart_consumer: rollout restart del Deployment `<servicio>`
  (misma tecnica que `kubectl rollout restart`: cambia una anotacion del template).
- compress_old_logs / restore_compressed_logs: no son operaciones de Kubernetes. Fallan
  con RuntimeError y el agente escala (no se inventa una equivalencia).
"""

from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from typing import Any


def _contenedor(pod: str, c: dict[str, Any]) -> str:
    partes = [f"contenedor {c.get('name', '?')} de {pod}: listo={c.get('ready')}"]
    partes.append(f"reinicios={c.get('restartCount', 0)}")
    for clave, rotulo in (("state", "ahora"), ("lastState", "antes")):
        for tipo, det in (c.get(clave) or {}).items():
            if tipo == "running":
                continue
            motivo = det.get("reason", "?")
            extra = f" codigo={det['exitCode']}" if "exitCode" in det else ""
            partes.append(f"{rotulo} {tipo} {motivo}{extra} {det.get('message', '')}".strip())
    return "; ".join(partes)


class BackendKubernetes:
    def __init__(
        self,
        api_url: str,
        token: str,
        namespace: str,
        ca_file: str | None = None,
        etiqueta_app: str = "app",
    ) -> None:
        self._api = api_url.rstrip("/")
        self._token = token
        self._ns = namespace
        self._etiqueta = etiqueta_app
        self._ssl = ssl.create_default_context(cafile=ca_file) if ca_file else None

    @classmethod
    def desde_entorno(cls) -> BackendKubernetes:
        """AIOPS_K8S_API, AIOPS_K8S_NAMESPACE y el token (AIOPS_K8S_TOKEN_FILE o
        AIOPS_K8S_TOKEN). AIOPS_K8S_CA_FILE: CA del API server (k3d usa una propia)."""
        token_file = os.environ.get("AIOPS_K8S_TOKEN_FILE", "").strip()
        if token_file:
            with open(token_file, encoding="utf-8") as f:
                token = f.read().strip()
        else:
            token = os.environ["AIOPS_K8S_TOKEN"]
        return cls(
            api_url=os.environ["AIOPS_K8S_API"],
            token=token,
            namespace=os.environ.get("AIOPS_K8S_NAMESPACE", "aiops-lab"),
            ca_file=os.environ.get("AIOPS_K8S_CA_FILE") or None,
        )

    def _pedir(self, metodo: str, ruta: str, cuerpo: Any, tipo: str, timeout_s: int) -> Any:
        datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
        req = urllib.request.Request(  # noqa: S310  (URL fija por configuracion)
            f"{self._api}{ruta}",
            data=datos,
            method=metodo,
            headers={"Authorization": f"Bearer {self._token}", "Content-Type": tipo},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout_s, context=self._ssl) as resp:  # noqa: S310
                return json.loads(resp.read().decode() or "{}")
        except urllib.error.HTTPError as exc:
            # 403 = el RBAC dijo que no: es informacion util para el escalamiento.
            msg = f"API de Kubernetes respondio {exc.code} en {metodo} {ruta}"
            raise RuntimeError(msg) from exc

    def eventos(self, servicio: str, maximo: int = 15) -> list[str]:
        """Solo lectura: estado de los contenedores de los pods `app=<servicio>` y los ultimos
        eventos de esos pods. Namespace y selector salen de la configuracion y del incidente."""
        selector = urllib.parse.urlencode({"labelSelector": f"{self._etiqueta}={servicio}"})
        pods = self._pedir(
            "GET", f"/api/v1/namespaces/{self._ns}/pods?{selector}", None, "application/json", 10
        ).get("items", [])
        if not pods:
            return [f"sin pods {self._etiqueta}={servicio} en {self._ns}"]
        lineas: list[str] = []
        nombres = set()
        for pod in pods:
            nombre = pod["metadata"]["name"]
            nombres.add(nombre)
            estado = pod.get("status", {})
            lineas.append(f"pod {nombre}: fase={estado.get('phase', '?')}")
            lineas += [_contenedor(nombre, c) for c in estado.get("containerStatuses", [])]
        campo = urllib.parse.urlencode({"fieldSelector": "involvedObject.kind=Pod"})
        crudos = self._pedir(
            "GET", f"/api/v1/namespaces/{self._ns}/events?{campo}", None, "application/json", 10
        ).get("items", [])
        propios = [e for e in crudos if e.get("involvedObject", {}).get("name") in nombres]
        propios.sort(key=lambda e: e.get("lastTimestamp") or e.get("eventTime") or "")
        for e in propios[-maximo:]:
            lineas.append(
                f"evento {e.get('type', '?')} {e.get('reason', '?')} "
                f"x{e.get('count', 1)}: {e.get('message', '')}"
            )
        return lineas

    def ejecutar(self, accion: str, servicio: str, timeout_s: int) -> str:
        if accion == "recreate_pod":
            selector = urllib.parse.urlencode({"labelSelector": f"{self._etiqueta}={servicio}"})
            res = self._pedir(
                "DELETE",
                f"/api/v1/namespaces/{self._ns}/pods?{selector}",
                None,
                "application/json",
                timeout_s,
            )
            borrados = [p["metadata"]["name"] for p in res.get("items", [])]
            if not borrados:
                raise RuntimeError(f"no hay pods {self._etiqueta}={servicio} en {self._ns}")
            return f"pods recreados en {self._ns}: {', '.join(borrados)}"
        if accion in ("restart_service", "restart_consumer"):
            ahora = datetime.now(UTC).isoformat()
            parche = {
                "spec": {"template": {"metadata": {"annotations": {"aiops/restartedAt": ahora}}}}
            }
            self._pedir(
                "PATCH",
                f"/apis/apps/v1/namespaces/{self._ns}/deployments/{servicio}",
                parche,
                "application/strategic-merge-patch+json",
                timeout_s,
            )
            return f"rollout restart de deployment/{servicio} en {self._ns}"
        raise RuntimeError(f"accion {accion!r} no soportada por el backend Kubernetes: escalar")
