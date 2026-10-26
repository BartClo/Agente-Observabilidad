"""Almacen de conocimiento contra pgvector real, con vectores deterministas."""

from __future__ import annotations

import os
from collections.abc import Iterator

import psycopg
import pytest

from rag import store
from rag.types import Documento, Fragmento

ORIGENES = ("repo",)


@pytest.fixture(autouse=True)
def _limpio() -> Iterator[None]:
    def borrar() -> None:
        with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
            conn.execute("DELETE FROM rag_documentos")

    borrar()
    yield
    borrar()


def v(i: int) -> list[float]:
    x = [0.0] * 1536
    x[i] = 1.0
    return x


def doc(
    nombre: str,
    servicios: tuple[str, ...] = (),
    tipo: str = "ficha",
    obsoleto: bool = False,
    origen: str = "repo",
) -> Documento:
    return Documento(nombre, origen, servicios, tipo, None, obsoleto, nombre, 1, 10, None)


def guardar(d: Documento, texto: str = "t", i: int = 0) -> int:
    return store.guardar_documento(d, [Fragmento(texto, 1, 0)], [v(i)])


def buscar(
    servicio: str | None = "checkout",
    k: int = 10,
    min_sim: float = 0.0,
    origenes: tuple[str, ...] = ORIGENES,
    excluir_tipos: tuple[str, ...] = (),
) -> list[str]:
    pasajes = store.buscar(
        v(0),
        servicio=servicio,
        k=k,
        min_sim=min_sim,
        origenes=origenes,
        excluir_tipos=excluir_tipos,
    )
    return [p.documento for p in pasajes]


def test_filtra_por_servicio_y_incluye_generales() -> None:
    guardar(doc("checkout", ("checkout",)))
    guardar(doc("api", ("api",)))
    guardar(doc("general"))
    assert set(buscar()) == {"checkout", "general"}
    assert set(buscar(servicio=None)) == {"checkout", "api", "general"}


def test_excluye_obsoletos_tipos_y_origenes() -> None:
    guardar(doc("viejo", obsoleto=True))
    guardar(doc("rb", tipo="runbook"))
    guardar(doc("subido", origen="subido"))
    guardar(doc("ok"))
    assert buscar(excluir_tipos=("runbook",)) == ["ok"]
    assert set(buscar(origenes=("repo", "subido"), excluir_tipos=("runbook",))) == {"ok", "subido"}


def test_piso_de_similitud() -> None:
    guardar(doc("lejano"), i=5)  # ortogonal a la consulta v(0): similitud 0
    guardar(doc("cercano"), i=0)
    assert buscar(min_sim=0.5) == ["cercano"]
    assert set(buscar(min_sim=0.0)) == {"cercano", "lejano"}


def test_orden_por_similitud_y_k() -> None:
    guardar(doc("a"), i=3)
    guardar(doc("b"), i=0)
    assert buscar(k=1) == ["b"]


def test_idempotente_por_sha() -> None:
    primero = guardar(doc("x"))
    assert guardar(doc("x")) == primero
    assert len(store.listar_documentos()) == 1


def test_borrar_documento_borra_fragmentos() -> None:
    doc_id = guardar(doc("x"))
    store.borrar_documento(doc_id)
    assert buscar() == []
    assert store.listar_documentos() == []


def test_largos_distintos_se_rechazan() -> None:
    with pytest.raises(ValueError, match="mismo largo"):
        store.guardar_documento(doc("x"), [Fragmento("a", 1, 0)], [])
