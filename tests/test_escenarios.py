"""Los escenarios del experimento apuntan a scripts que existen y a categorias reales."""

from __future__ import annotations

import os
import shutil
import subprocess

import pytest

from domain.aiops_core.catalogo import CATALOGO, categoria_para_alerta
from scripts.experimento import ESCENARIOS, RAIZ, VARIANTES


def test_cada_escenario_tiene_sus_scripts_y_su_categoria() -> None:
    for cat, esc in ESCENARIOS.items():
        assert cat in CATALOGO
        assert categoria_para_alerta(esc.alertname) is CATALOGO[cat]
        assert (RAIZ / "scripts" / "fallas" / esc.falla).exists(), esc.falla
        if esc.recuperar:
            assert (RAIZ / "scripts" / "fallas" / esc.recuperar).exists(), esc.recuperar


def test_cola_detenida_es_remediable_en_el_laboratorio() -> None:
    esc = ESCENARIOS["cola_detenida"]
    assert CATALOGO["cola_detenida"].remediable
    assert esc.usa_k8s and esc.recuperar == "recuperar_cola.sh"
    assert 'queue="worker"' in esc.anomalia  # la metrica del consumidor, no la del broker


def test_cada_variante_de_la_tabla_13_tiene_inyeccion_y_reversion() -> None:
    assert set(VARIANTES) == {
        "pod_fallido/config_invalida",
        "pod_fallido/imagen_inexistente",
        "servicio_detenido/variable_ausente",
        "cola_detenida/mensaje_venenoso",
    }
    for clave, esc in VARIANTES.items():
        base = ESCENARIOS[clave.partition("/")[0]]
        assert (esc.alertname, esc.servicio) == (base.alertname, base.servicio)
        assert (RAIZ / "scripts/fallas" / esc.falla).exists() and esc.recuperar
        assert (RAIZ / "scripts/fallas" / esc.recuperar).exists()


def test_ningun_script_de_k8s_fija_el_namespace() -> None:
    for script in (RAIZ / "scripts/fallas").glob("*.sh"):
        assert "-n aiops-lab" not in script.read_text(encoding="utf-8"), script.name


@pytest.mark.skipif(shutil.which("sh") is None, reason="sin sh")
@pytest.mark.parametrize("script", ["pod_fallido.sh", "var_config_invalida.sh", "_k8s_un_pod.sh"])
def test_no_inyecta_en_un_namespace_no_declarado(script: str) -> None:
    """Corta antes de llegar a kubectl."""
    r = subprocess.run(
        ["sh", f"scripts/fallas/{script}", "api"],
        cwd=RAIZ,
        env={**os.environ, "EXP_NAMESPACE": "produccion", "PATH": os.environ["PATH"]},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert r.returncode == 3 and "no declarado" in r.stderr
