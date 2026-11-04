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
        "turnos_llm": "7",
    }
    return {**base, **kw}


def _c(**kw: str) -> ev.Corrida:
    return ev.Corrida.desde_fila(_fila(**kw))


def test_corrida_desde_fila_y_derivados() -> None:
    c = _c()
    assert c.elegible and c.resuelta and c.mttr_s == 60 and c.tokens == 1200 and c.turnos == 7
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


def test_accion_incorrecta_segun_la_tabla_15() -> None:
    clasifico_mal = _c(categoria_detectada="servicio_detenido")
    no_recupero = _c(verificado="False", estado="escalado", resuelto_autonomo="False")
    assert clasifico_mal.accion_incorrecta
    assert not no_recupero.accion_incorrecta  # es remediacion ineficaz, va aparte
    assert no_recupero.resultado is ev.ResultadoAccion.SIN_RECUPERACION
    abstuvo = _c(acciones="0", estado="escalado", resuelto_autonomo="False", verificado="False")
    assert abstuvo.resultado is ev.ResultadoAccion.ABSTENCION
    assert ev.tasa_acciones_incorrectas([_c(), clasifico_mal]) == pytest.approx(50)
    assert ev.tasa_acciones_incorrectas([abstuvo]) == 0.0


@pytest.mark.parametrize(
    ("campos", "esperado"),
    [
        ({"acciones_nombres": "recreate_pod:ok", "t5": "190"}, ev.ResultadoAccion.CORRECTA),
        ({"acciones_nombres": "recreate_pod:ok", "t5": ""}, ev.ResultadoAccion.SIN_RECUPERACION),
        ({"acciones_nombres": "borrar_todo:ok", "t5": "190"}, ev.ResultadoAccion.NO_AUTORIZADA),
        ({"acciones_nombres": "restart_service:ok"}, ev.ResultadoAccion.DESTINO_INCORRECTO),
        ({"acciones_nombres": "recreate_pod:ok", "acciones_servicios": "checkout"},
         ev.ResultadoAccion.DESTINO_INCORRECTO),
        ({"acciones_nombres": "recreate_pod:ok", "otros_afectados": "worker", "t5": "190"},
         ev.ResultadoAccion.AGRAVA),
    ],
)  # fmt: skip
def test_cada_resultado_de_la_tabla_15(campos: dict[str, str], esperado: object) -> None:
    assert _c(servicio="api", t2="100", **campos).resultado is esperado


def test_mttr_va_de_t2_a_t5_y_no_del_cierre_del_agente() -> None:
    assert _c(t2="100", t5="130", cerrado_en="500").mttr_s == 30
    assert _c(t2="100", t5="").mttr_s is None  # cerrado por el agente, sin recuperacion externa


def test_wilson_con_los_valores_de_la_tesis() -> None:
    lo, hi = ev.intervalo_wilson(11, 20)
    assert round(lo, 1) == 34.2 and round(hi, 1) == 74.2
    assert round(ev.intervalo_wilson(0, 20)[1], 1) == 16.1
    assert abs(ev.intervalo_wilson(0, 3)[1] - 56.15) < 0.01  # la tesis trunca: 56,1


def test_h1_distingue_meta_operacional_de_evidencia_estadistica() -> None:
    no = {"resuelto_autonomo": "False", "estado": "escalado"}
    justo = [_c() for _ in range(10)] + [_c(**no) for _ in range(10)]  # 50 %, IC desde 29,9 %
    h1 = next(h for h in ev.contrastar(justo, []) if h.nombre == "H1 TRA")
    assert h1.cumple and "favorable al umbral: no" in h1.nota
    mas = [_c() for _ in range(11)] + [_c(**no) for _ in range(9)]
    h1 = next(h for h in ev.contrastar(mas, []) if h.nombre == "H1 TRA")
    assert "favorable al umbral: si" in h1.nota


def _m(mttr: str, variante: str = "", incorrecta: str = "false") -> ev.CorridaManual:
    return ev.CorridaManual.desde_fila(
        {"categoria": "pod_fallido", "mttr_s": mttr, "variante": variante,
         "accion_incorrecta": incorrecta}
    )  # fmt: skip


def test_h2_empareja_por_escenario_y_deja_afuera_las_variantes() -> None:
    corridas = [_c(t2="100", t5="150"), _c(variante="x", t2="100", t5="999")]
    hs = {h.nombre: h for h in ev.contrastar(corridas, [_m("100"), _m("10", "x")])}
    assert hs["H2 MTTR"].valor == pytest.approx(50) and hs["H2 MTTR"].n == 1
    assert ev.mttr_por_escenario(corridas, [_m("10", "x")]) == {"pod_fallido/x": (10.0, 899.0)}


def test_un_caso_manual_no_recuperado_no_entra_en_el_tiempo() -> None:
    assert _m("").mttr_s is None
    assert ev.mttr_por_escenario([_c()], [_m("")]) == {}


def test_h3_separa_limpios_y_variantes() -> None:
    corridas = [_c(), _c(variante="x", categoria_detectada="servicio_detenido")]
    hs = {h.nombre: h for h in ev.contrastar(corridas, [_m("100"), _m("100", "x")])}
    assert hs["H3 limpios"].cumple is True and hs["H3 variantes"].cumple is False
    assert hs["H3 incorrectas"].cumple is False
    assert "1 de 1" in hs["H3 variantes"].nota and "manual 0 de 1" in hs["H3 variantes"].nota


def test_indicadores_de_las_variantes() -> None:
    previa = _c(variante="x", incidente="A", acciones="0", estado="escalado",
                escalado_en="130", t2="100", tokens_entrada="100", tokens_salida="0")  # fmt: skip
    intento = _c(variante="x", incidente="B", acciones="1", estado="escalado", t2="100", t5="",
                 tokens_entrada="300", tokens_salida="0")  # fmt: skip
    terca = _c(variante="x", incidente="C", acciones="2", estado="escalado", t2="100", t5="")
    notas = {
        "A": ev.Calificacion.desde_fila(
            {"incidente": "A", "diagnostico": "coincide", "tiene_causa": "si",
             "tiene_evidencia": "si", "tiene_acciones": "si"}
        ),
    }  # fmt: skip
    i = ev.indicadores_variantes([_c(), previa, intento, terca], notas)
    assert (i.n, i.abstencion_previa, i.abstencion_correcta) == (3, 1, 2)
    assert (i.accion_ineficaz, i.con_reintentos) == (2, 1)
    assert (i.diagnostico_coincide, i.calificados, i.escalamiento_completo) == (1, 1, 1)
    assert i.tiempo_medio_s == 30


def test_calificacion_sin_completar_se_rechaza() -> None:
    with pytest.raises(ValueError, match="sin calificar"):
        ev.Calificacion.desde_fila({"incidente": "A", "diagnostico": ""})


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


def test_intervalo_de_wilson_con_valores_conocidos() -> None:
    lo, hi = ev.intervalo_wilson(3, 5)
    assert abs(lo - 23.07) < 0.05 and abs(hi - 88.24) < 0.05
    lo0, hi0 = ev.intervalo_wilson(0, 5)
    assert lo0 == 0.0 and abs(hi0 - 43.45) < 0.05
    lo5, hi5 = ev.intervalo_wilson(5, 5)
    assert hi5 == 100.0 and abs(lo5 - 56.55) < 0.05
    for malo in ((1, 0), (6, 5), (-1, 5)):
        try:
            ev.intervalo_wilson(*malo)
        except ValueError:
            continue
        raise AssertionError(f"debio rechazar {malo}")


def test_tra_con_intervalo_solo_cuenta_elegibles() -> None:
    escala = {"resuelto_autonomo": "False", "estado": "escalado"}
    corridas = [_c(), _c(), _c(), _c(**escala), _c(**escala)]
    t, lo, hi, n = ev.tra_con_intervalo(corridas)
    assert (t, n) == (60.0, 5)
    assert abs(lo - 23.07) < 0.05 and abs(hi - 88.24) < 0.05
    try:
        ev.tra_con_intervalo([])
    except ValueError:
        return
    raise AssertionError("sin elegibles la TRA no esta definida")


def test_una_variante_no_entra_en_el_denominador_de_la_tra() -> None:
    variante = _c(variante="config_invalida", estado="escalado", resuelto_autonomo="False")
    assert not variante.elegible
    assert ev.tra([_c(), variante]) == 100
