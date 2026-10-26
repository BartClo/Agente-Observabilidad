"""Lectura e indexado de documentos. Embedder simulado; el almacen es pgvector real."""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import date

import psycopg
import pytest

from rag import ingest, store

MD = """---
servicios: checkout, api
tipo: postmortem
vigente_desde: 2026-08-01
obsoleto: false
---
# Titulo

Cuerpo del documento.
"""


def pdf_con_texto(textos: list[str]) -> bytes:
    """PDF minimo valido con una pagina por texto (xref calculado a mano)."""
    objs: list[bytes] = []
    n_pag = len(textos)
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(n_pag))
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {n_pag} >>".encode())
    fuente = 3 + 2 * n_pag
    for i, t in enumerate(textos):
        cont = f"BT /F1 12 Tf 20 100 Td ({t}) Tj ET".encode()
        objs.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] /Contents {4 + 2 * i} 0 R "
            f"/Resources << /Font << /F1 {fuente} 0 R >> >> >>".encode()
        )
        objs.append(b"<< /Length %d >>\nstream\n" % len(cont) + cont + b"\nendstream")
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out = b"%PDF-1.4\n"
    offs = []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offs:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    return out


def falso_embed(textos: list[str]) -> list[list[float]]:
    return [[1.0] + [0.0] * 1535 for _ in textos]


@pytest.fixture
def _limpio() -> Iterator[None]:
    def borrar() -> None:
        with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
            conn.execute("DELETE FROM rag_documentos")

    borrar()
    yield
    borrar()


def test_markdown_con_encabezado() -> None:
    doc, paginas = ingest.leer_markdown(MD, "pm-checkout.md")
    assert doc.servicios == ("checkout", "api")
    assert doc.tipo == "postmortem"
    assert doc.vigente_desde == date(2026, 8, 1)
    assert not doc.obsoleto and doc.origen == "repo"
    assert paginas == [(None, "# Titulo\n\nCuerpo del documento.\n")]


def test_markdown_sin_encabezado_es_general_y_tipo_otro() -> None:
    doc, paginas = ingest.leer_markdown("solo texto", "x.md")
    assert doc.servicios == () and doc.tipo == "otro" and doc.vigente_desde is None
    assert paginas == [(None, "solo texto")]


def test_markdown_obsoleto_y_fecha_invalida() -> None:
    doc, _ = ingest.leer_markdown("---\nobsoleto: true\n---\nx", "v.md")
    assert doc.obsoleto
    with pytest.raises(ingest.ErrorIngesta, match="fecha"):
        ingest.leer_markdown("---\nvigente_desde: ayer\n---\nx", "v.md")


def test_pdf_extrae_texto_por_pagina() -> None:
    doc, paginas = ingest.leer_pdf(
        pdf_con_texto(["Hola checkout", "Segunda pagina"]), "m.pdf", subido_por="admin"
    )
    assert doc.origen == "subido" and doc.paginas == 2 and doc.subido_por == "admin"
    assert [n for n, _ in paginas] == [1, 2]
    assert "Hola checkout" in paginas[0][1] and "Segunda pagina" in paginas[1][1]


def test_pdf_rechaza_lo_que_no_es_pdf_o_es_grande_o_esta_roto() -> None:
    with pytest.raises(ingest.ErrorIngesta, match="no es un PDF"):
        ingest.leer_pdf(b"MZ\x90\x00 programa.exe", "a.pdf")
    with pytest.raises(ingest.ErrorIngesta, match="5 MB"):
        ingest.leer_pdf(b"%PDF-" + b"0" * ingest.MAX_PDF_BYTES, "g.pdf")
    with pytest.raises(ingest.ErrorIngesta, match="no se pudo leer"):
        ingest.leer_pdf(b"%PDF-1.4 basura sin estructura", "r.pdf")


def test_pdf_sin_texto_se_rechaza() -> None:
    with pytest.raises(ingest.ErrorIngesta, match="sin texto|no tiene texto"):
        ingest.leer_pdf(pdf_con_texto([""]), "vacio.pdf")


@pytest.mark.usefixtures("_limpio")
def test_indexar_enmascara_secretos_y_es_idempotente() -> None:
    doc, paginas = ingest.leer_markdown(
        "---\nservicios: api\n---\nconectar con password=hunter2 y admin@acme.com", "s.md"
    )
    llamadas: list[int] = []

    def embed(t: list[str]) -> list[list[float]]:
        llamadas.append(len(t))
        return falso_embed(t)

    doc_id = ingest.indexar(doc, paginas, embed)
    assert ingest.indexar(doc, paginas, embed) == doc_id
    assert len(llamadas) == 1  # el segundo indexado no gasta API
    (p,) = store.buscar(falso_embed([""])[0], servicio="api", k=5, min_sim=0.0, origenes=("repo",))
    assert "hunter2" not in p.contenido and "admin@acme.com" not in p.contenido
    assert "[SECRETO]" in p.contenido and "[EMAIL]" in p.contenido


def test_indexar_sin_texto_falla() -> None:
    doc, paginas = ingest.leer_markdown("---\ntipo: guia\n---\n   ", "v.md")
    with pytest.raises(ingest.ErrorIngesta, match="no tiene texto"):
        ingest.indexar(doc, paginas, falso_embed)
