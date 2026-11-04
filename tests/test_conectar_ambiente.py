"""Asistente de conexion: propone, pero nunca activa."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from infra import perfil as perfiles
from scripts import conectar_ambiente as ca

REGLAS = {
    "data": {
        "groups": [
            {
                "rules": [
                    {"name": "KubePodCrashLooping", "type": "alerting"},
                    {"name": "ServicioCaido", "type": "alerting"},
                    {"name": "DiskAlmostFull", "type": "alerting"},
                    {"name": "LatenciaAlta", "type": "alerting"},
                    {"name": "registro:rate", "type": "recording"},
                ]
            }
        ]
    }
}
METRICAS = ["up", "kube_pod_status_ready"]


def _leer(url: str) -> Any:
    return REGLAS if url.endswith("/rules") else {"data": METRICAS}


def test_borrador_clasifica_y_avisa_lo_que_no_puede() -> None:
    perfil, avisos = ca.borrador("qa", REGLAS, METRICAS)
    assert {c["id"]: c["alertas"] for c in perfil["categorias"]} == {
        "pod_fallido": ["KubePodCrashLooping"],
        "servicio_detenido": ["ServicioCaido"],
    }
    assert all(c["nivel"] == 1 for c in perfil["categorias"])
    assert any("LatenciaAlta" in a for a in avisos)
    assert any("disco_lleno" in a for a in avisos)  # sin su metrica no entra


def test_el_borrador_no_carga_hasta_que_un_humano_lo_aprueba(tmp_path: Path) -> None:
    salida = tmp_path / "p" / "qa.yaml"
    assert (
        ca.main(["--prometheus", "http://p", "--entorno", "qa", "--salida", str(salida)], _leer)
        == 0
    )
    with pytest.raises(perfiles.PerfilInvalido, match="sin aprobar"):
        perfiles.cargar(salida)
    datos = yaml.safe_load(salida.read_text(encoding="utf-8"))
    datos.update(aprobado=True, aprobado_por="ana")
    assert perfiles.parsear(datos).entorno == "qa"


def test_no_pisa_un_perfil_existente(tmp_path: Path) -> None:
    salida = tmp_path / "qa.yaml"
    salida.write_text("original", encoding="utf-8")
    assert (
        ca.main(["--prometheus", "http://p", "--entorno", "qa", "--salida", str(salida)], _leer)
        == 1
    )
    assert salida.read_text(encoding="utf-8") == "original"
