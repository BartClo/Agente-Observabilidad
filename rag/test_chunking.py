import pytest

from rag.chunking import fragmentar


def test_texto_vacio_no_da_fragmentos() -> None:
    assert fragmentar([(None, "")]) == []
    assert fragmentar([]) == []


def test_texto_corto_da_un_fragmento() -> None:
    (f,) = fragmentar([(None, "hola mundo")], size=100, overlap=10)
    assert (f.contenido, f.pagina, f.orden) == ("hola mundo", None, 0)


def test_texto_largo_solapa_y_numera() -> None:
    fr = fragmentar([(None, "a" * 25)], size=10, overlap=4)
    assert len(fr) == 4  # inicios 0, 6, 12, 18; el ultimo ya llega al final
    assert [f.orden for f in fr] == [0, 1, 2, 3]


def test_un_fragmento_nunca_cruza_de_pagina() -> None:
    fr = fragmentar([(1, "a" * 15), (2, "b" * 15)], size=10, overlap=2)
    assert {f.pagina for f in fr if "a" in f.contenido} == {1}
    assert {f.pagina for f in fr if "b" in f.contenido} == {2}
    assert [f.orden for f in fr] == list(range(len(fr)))


def test_size_debe_ser_mayor_que_overlap() -> None:
    with pytest.raises(ValueError):
        fragmentar([(None, "algo")], size=10, overlap=10)
