"""Los escenarios del experimento apuntan a scripts que existen y a categorias reales."""

from __future__ import annotations

from domain.aiops_core.catalogo import CATALOGO, categoria_para_alerta
from scripts.experimento import ESCENARIOS, RAIZ


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
