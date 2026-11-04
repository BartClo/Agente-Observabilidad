"""Perfil de ambiente: se valida entero al cargar y, sin perfil, nada cambia."""

from __future__ import annotations

import copy
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

from domain.aiops_core.catalogo import CATALOGO, categoria_para_alerta, restaurar_catalogo
from domain.aiops_core.modelos import NivelAutonomia
from infra import perfil as perfiles
from infra.observabilidad import PrometheusLoki

BASE: dict[str, Any] = {
    "version": 1,
    "aprobado": True,
    "aprobado_por": "ana@equipo",
    "entorno": "qa",
    "observabilidad": {"etiqueta_servicio": "app", "etiqueta_logs": "container"},
    "consultas": {"salud_http": 'min(sonda_ok{app="$servicio"})'},
    "categorias": [
        {
            "id": "web_caida",
            "alertas": ["WebNoResponde"],
            "runbook": "RB-001",
            "senal": {"metrica": "salud_http", "operador": ">=", "umbral": 1},
            "accion": "restart_service",
        }
    ],
}


@pytest.fixture(autouse=True)
def _limpio(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv("AIOPS_PERFIL", raising=False)
    yield
    perfiles._cargar_y_activar.cache_clear()
    restaurar_catalogo()


def _con(**cambios: Any) -> dict[str, Any]:
    return {**copy.deepcopy(BASE), **cambios}


def _categoria(**cambios: Any) -> dict[str, Any]:
    return _con(categorias=[{**BASE["categorias"][0], **cambios}])


def test_sin_perfil_el_catalogo_no_cambia() -> None:
    assert perfiles.activo() is None
    assert categoria_para_alerta("ServiceDown") is not None
    assert len(CATALOGO) == 5


def test_perfil_reemplaza_catalogo_y_consultas(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ruta = tmp_path / "perfil.yaml"
    ruta.write_text(yaml.safe_dump(BASE), encoding="utf-8")
    monkeypatch.setenv("AIOPS_PERFIL", str(ruta))
    monkeypatch.setenv("AIOPS_PROMETHEUS_URL", "http://p")
    perfil = perfiles.activo()
    assert perfil is not None and perfil.entorno == "qa"
    assert categoria_para_alerta("ServiceDown") is None
    cat = categoria_para_alerta("WebNoResponde")
    assert cat is not None and cat.accion == "restart_service"

    adaptador = PrometheusLoki.desde_entorno()
    urls: list[str] = []

    def falso(url: str) -> dict[str, Any]:
        urls.append(url)
        return {"data": {"result": [{"value": [0, "1"]}]}}

    monkeypatch.setattr(adaptador, "_get", falso)
    assert adaptador.metrica("web-1", "salud_http") == 1.0
    assert "sonda_ok" in urls[0] and "web-1" in urls[0]


def test_nivel_por_defecto_es_observacion() -> None:
    assert perfiles.parsear(BASE).niveles["web_caida"] is NivelAutonomia.RECOMIENDA


@pytest.mark.parametrize(
    ("datos", "mensaje"),
    [
        (_con(aprobado=False), "sin aprobar"),
        (_con(aprobado="true"), "sin aprobar"),
        (_con(aprobado_por=""), "sin aprobar"),
        (_con(version=2), "version"),
        (_con(categorias=[]), "categorias"),
        (_con(extra=1), "claves desconocidas"),
        (_con(entorno=None), "entorno"),
        (_con(consultas={"x": "up"}), r"\$servicio"),
        (_categoria(accion="rm_rf"), "fuera de la lista"),
        (_categoria(runbook="RB-999"), "runbook"),
        (_categoria(senal={"metrica": "nada", "operador": ">=", "umbral": 1}), "no tiene consulta"),
        (_categoria(senal={"metrica": "up", "operador": "~", "umbral": 1}), "senal"),
        (_categoria(nivel=9), "nivel"),
        (_con(kubernetes={"namespace": ["a"]}), "claves desconocidas"),
        (_con(observabilidad={"etiqueta_servicio": 'a"}'}), "etiqueta"),
    ],
)
def test_perfil_invalido_no_carga(datos: dict[str, Any], mensaje: str) -> None:
    with pytest.raises(perfiles.PerfilInvalido, match=mensaje):
        perfiles.parsear(datos)


def test_alerta_en_dos_categorias_no_carga() -> None:
    otra = {**BASE["categorias"][0], "id": "otra"}
    with pytest.raises(perfiles.PerfilInvalido, match="dos categorias"):
        perfiles.parsear(_con(categorias=[BASE["categorias"][0], otra]))


def test_archivo_ilegible(tmp_path: Path) -> None:
    with pytest.raises(perfiles.PerfilInvalido, match="no se pudo leer"):
        perfiles.cargar(tmp_path / "no-existe.yaml")
