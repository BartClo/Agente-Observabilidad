"""El corpus sintetico cumple los criterios con los que se escribio (corpus/LEEME.txt):
bien formado, con resultados mezclados, con distractores y sin hablar de como se prueba
el agente (eso lo haria 'ayudar demasiado')."""

from __future__ import annotations

from pathlib import Path

import pytest

from rag import ingest

CORPUS = Path(__file__).resolve().parent.parent / "corpus"
ARCHIVOS = sorted(CORPUS.glob("*.md"))
PROHIBIDAS = ("inyec", "experimento", "escenario", "tesis", "el agente debe")
SERVICIOS_DEL_LAB = {"api", "checkout", "worker"}


def _leidos() -> list[tuple[Path, str]]:
    return [(p, p.read_text(encoding="utf-8")) for p in ARCHIVOS]


def test_hay_corpus_suficiente() -> None:
    assert len(ARCHIVOS) >= 15


@pytest.mark.parametrize("archivo", ARCHIVOS, ids=lambda p: p.name)
def test_cada_documento_esta_bien_formado(archivo: Path) -> None:
    texto = archivo.read_text(encoding="utf-8")
    doc, paginas = ingest.leer_markdown(texto, archivo.name)
    assert doc.tipo != "otro", "declarar el tipo en el encabezado"
    assert doc.vigente_desde is not None
    assert "origen_dato: sintetico" in texto
    assert paginas[0][1].strip(), "sin cuerpo"


@pytest.mark.parametrize("archivo", ARCHIVOS, ids=lambda p: p.name)
def test_no_habla_de_como_se_prueba_el_agente(archivo: Path) -> None:
    texto = archivo.read_text(encoding="utf-8").lower()
    assert not [w for w in PROHIBIDAS if w in texto], archivo.name


def test_hay_obsoleto_distractores_y_cobertura_de_los_tres_servicios() -> None:
    docs = {p.name: ingest.leer_markdown(t, p.name)[0] for p, t in _leidos()}
    assert any(d.obsoleto for d in docs.values())
    distractores = [
        d for d in docs.values() if d.servicios and not set(d.servicios) & SERVICIOS_DEL_LAB
    ]
    assert len(distractores) >= 2  # billing, gateway
    for srv in SERVICIOS_DEL_LAB:
        assert any(srv in d.servicios and d.tipo == "ficha" for d in docs.values()), srv


def test_los_postmortems_tienen_resultados_mezclados() -> None:
    pms = [t for p, t in _leidos() if p.name.startswith("postmortem-")]
    assert len(pms) >= 6
    funciono = [t for t in pms if "**Qué funcionó" in t]
    no_funciono = [t for t in pms if "**Qué no funcionó" in t]
    assert len(funciono) >= 2 and len(no_funciono) >= 2
    # y ninguno resuelve todo con una receta de un paso
    assert all("**Causa raíz" in t and "**Acciones" in t for t in pms)
