"""Evaluacion de la tesis (Fase 7): las definiciones que deciden H1-H3."""

from __future__ import annotations

import pytest

from domain.aiops_core import evaluacion as ev


def _fila(**kw: str) -> dict[str, str]:
    base = {
        "categoria_esperada": "pod_fallido",
        "categoria_detectada": "pod_fallido",
        "estado": "resuelto",
        "resuelto_autonomo": "True",
        "verificado": "True",
        "acciones": "1",
        "disparada_en": "100",
        "cerrado_en": "160",
        "tokens_entrada": "1000",
        "tokens_salida": "200",
    }
    return {**base, **kw}


def _c(**kw: str) -> ev.Corrida:
    return ev.Corrida.desde_fila(_fila(**kw))


def test_corrida_desde_fila_y_derivados() -> None:
    c = _c()
    assert c.elegible and c.resuelta and c.mttr_s == 60 and c.tokens == 1200
    assert not c.accion_incorrecta
    sin_cierre = _c(
        estado="escalado",
        resuelto_autonomo="False",
        verificado="False",
        acciones="0",
        cerrado_en="",
    )
    assert sin_cierre.mttr_s is None and not sin_cierre.accion_incorrecta
    with pytest.raises(ValueError, match="desconocida"):
        _c(categoria_esperada="inventada")


def test_elegibilidad_sale_de_la_falla_inyectada_no_del_agente() -> None:
    """Un agente que clasifica mal no achica su denominador: la corrida sigue contando
    como elegible (y como no resuelta)."""
    mal = _c(
        categoria_detectada="certificado_por_vencer",
        estado="escalado",
        resuelto_autonomo="False",
        verificado="False",
        acciones="0",
    )
    assert mal.elegible
    assert ev.tra([_c(), mal]) == pytest.approx(50)
    # certificado_por_vencer no tiene accion: nunca es elegible
    cert = _c(
        categoria_esperada="certificado_por_vencer",
        categoria_detectada="certificado_por_vencer",
        estado="escalado",
        resuelto_autonomo="False",
        verificado="False",
        acciones="0",
    )
    assert not cert.elegible
    assert ev.tra([_c(), cert]) == pytest.approx(100)
    with pytest.raises(ValueError):
        ev.tra([cert])


def test_accion_incorrecta() -> None:
    clasifico_mal = _c(categoria_detectada="servicio_detenido")
    no_recupero = _c(verificado="False", estado="escalado", resuelto_autonomo="False")
    assert clasifico_mal.accion_incorrecta and no_recupero.accion_incorrecta
    # sobre las corridas con accion; abstenerse (0 acciones) no cuenta
    abstuvo = _c(acciones="0", estado="escalado", resuelto_autonomo="False", verificado="False")
    assert ev.tasa_acciones_incorrectas([_c(), clasifico_mal, abstuvo]) == pytest.approx(50)
    assert ev.tasa_acciones_incorrectas([abstuvo]) == 0.0


def test_mttr_y_precision() -> None:
    assert ev.mttr([_c(cerrado_en="160"), _c(cerrado_en="220")]) == pytest.approx(90)
    with pytest.raises(ValueError):
        ev.mttr([_c(estado="escalado", verificado="False")])
    assert ev.precision_clasificacion([_c(), _c(categoria_detectada="")]) == pytest.approx(50)
    with pytest.raises(ValueError):
        ev.precision_clasificacion([])


def test_contrastar_cumple_y_no_cumple() -> None:
    base = [
        ev.CorridaManual.desde_fila(
            {"categoria": "pod_fallido", "mttr_s": "300", "accion_incorrecta": "false"}
        ),
        ev.CorridaManual.desde_fila(
            {"categoria": "pod_fallido", "mttr_s": "500", "accion_incorrecta": "true"}
        ),
    ]
    hs = {h.nombre: h for h in ev.contrastar([_c(), _c(cerrado_en="200")], base)}
    assert hs["H1 TRA"].cumple and hs["H1 TRA"].valor == 100
    # base 400s, agente 80s -> 80% de reduccion
    assert hs["H2 MTTR"].cumple and hs["H2 MTTR"].valor == pytest.approx(80)
    assert hs["H3 incorrectas"].cumple  # 0% vs 50%

    lento = [_c(cerrado_en="500")]  # 400s, igual que la base
    hs = {h.nombre: h for h in ev.contrastar(lento, base)}
    assert hs["H2 MTTR"].cumple is False


def test_contrastar_sin_datos_no_inventa_resultado() -> None:
    hs = {
        h.nombre: h
        for h in ev.contrastar(
            [
                _c(
                    categoria_esperada="certificado_por_vencer",
                    acciones="0",
                    estado="escalado",
                    resuelto_autonomo="False",
                    verificado="False",
                )
            ],
            [],
        )
    }
    assert hs["H1 TRA"].cumple is None
    assert hs["H2 MTTR"].cumple is None
    assert hs["H3 incorrectas"].cumple is None


def test_linea_base_valida() -> None:
    with pytest.raises(ValueError, match="mttr_s positivo"):
        ev.CorridaManual.desde_fila({"categoria": "pod_fallido", "mttr_s": "0"})
    with pytest.raises(ValueError, match="desconocida"):
        ev.CorridaManual.desde_fila({"categoria": "x", "mttr_s": "10"})
