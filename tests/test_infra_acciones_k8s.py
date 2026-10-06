"""BackendKubernetes con HTTP falso: valida que pegue a la ruta/verbo correctos, que
el namespace no lo decida el llamador y que los errores salgan como RuntimeError (lo
que Ciclo atrapa para registrar la accion fallida y escalar)."""

from __future__ import annotations

import io
import json
import urllib.error
from typing import Any

import pytest

from infra.acciones_k8s import BackendKubernetes


class _Resp(io.BytesIO):
    def __enter__(self) -> _Resp:
        return self

    def __exit__(self, *a: object) -> None:
        pass


@pytest.fixture
def llamadas(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    registro: list[Any] = []

    def falso_urlopen(req: Any, timeout: float, context: Any) -> _Resp:
        registro.append(req)
        if "pods" in req.full_url:
            items = [] if "app%3Dvacio" in req.full_url else [{"metadata": {"name": "api-1"}}]
            return _Resp(json.dumps({"items": items}).encode())
        if "prohibido" in req.full_url:
            raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, None)  # type: ignore[arg-type]
        return _Resp(b"{}")

    monkeypatch.setattr("urllib.request.urlopen", falso_urlopen)
    return registro


def _backend() -> BackendKubernetes:
    return BackendKubernetes("https://k8s:6443", "tok", "aiops-lab")


def test_recreate_pod_borra_por_label_en_el_namespace_fijo(llamadas: list[Any]) -> None:
    res = _backend().ejecutar("recreate_pod", "api", 30)
    req = llamadas[0]
    assert req.get_method() == "DELETE"
    assert req.full_url.startswith("https://k8s:6443/api/v1/namespaces/aiops-lab/pods?")
    assert "labelSelector=app%3Dapi" in req.full_url
    assert req.headers["Authorization"] == "Bearer tok"
    assert "api-1" in res


def test_recreate_pod_sin_pods_falla_en_vez_de_mentir_exito(llamadas: list[Any]) -> None:
    with pytest.raises(RuntimeError, match="no hay pods"):
        _backend().ejecutar("recreate_pod", "vacio", 30)


def test_restart_service_parchea_el_deployment(llamadas: list[Any]) -> None:
    _backend().ejecutar("restart_service", "checkout", 30)
    req = llamadas[0]
    assert req.get_method() == "PATCH"
    assert req.full_url.endswith("/apis/apps/v1/namespaces/aiops-lab/deployments/checkout")
    assert req.headers["Content-type"] == "application/strategic-merge-patch+json"
    cuerpo = json.loads(req.data)
    assert "aiops/restartedAt" in cuerpo["spec"]["template"]["metadata"]["annotations"]


def test_rbac_denegado_y_accion_no_soportada_son_runtime_error(llamadas: list[Any]) -> None:
    with pytest.raises(RuntimeError, match="403"):
        _backend().ejecutar("restart_consumer", "prohibido", 30)
    with pytest.raises(RuntimeError, match="no soportada"):
        _backend().ejecutar("compress_old_logs", "billing", 30)
    assert len(llamadas) == 1  # la accion no soportada ni siquiera llama a la API


def test_desde_entorno_lee_token_de_archivo(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    token = tmp_path / "token"
    token.write_text("secreto\n")
    monkeypatch.setenv("AIOPS_K8S_API", "https://k8s:6443/")
    monkeypatch.setenv("AIOPS_K8S_TOKEN_FILE", str(token))
    monkeypatch.delenv("AIOPS_K8S_CA_FILE", raising=False)
    b = BackendKubernetes.desde_entorno()
    assert b._token == "secreto" and b._ns == "aiops-lab" and b._api == "https://k8s:6443"
