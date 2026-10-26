"""CLI del conocimiento y tool de busqueda del chat (embedder y almacen simulados)."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest

from agents.aiops import chat, conocimiento
from rag import cli, ingest
from rag.types import Documento, Pasaje


@pytest.fixture
def indexados(monkeypatch: pytest.MonkeyPatch) -> list[Documento]:
    vistos: list[Documento] = []

    def indexar(doc: Documento, paginas: ingest.Paginas) -> int:
        vistos.append(doc)
        return len(vistos)

    monkeypatch.setattr(ingest, "indexar", indexar)
    return vistos


def test_indexar_carpeta_toma_md_y_pdf_y_aplica_el_tipo_por_defecto(
    tmp_path: Path, indexados: list[Documento]
) -> None:
    (tmp_path / "a.md").write_text("---\ntipo: postmortem\n---\nx", encoding="utf-8")
    (tmp_path / "b.md").write_text("sin encabezado", encoding="utf-8")
    (tmp_path / "ignorar.txt").write_text("no", encoding="utf-8")
    res = cli.indexar_ruta(tmp_path, tipo="runbook")
    assert [n for n, _ in res] == ["a.md", "b.md"]
    assert {d.nombre: d.tipo for d in indexados} == {"a.md": "postmortem", "b.md": "runbook"}


def test_indexar_un_archivo_con_origen(tmp_path: Path, indexados: list[Documento]) -> None:
    f = tmp_path / "x.md"
    f.write_text("hola", encoding="utf-8")
    cli.indexar_ruta(f, origen="subido")
    assert indexados[0].origen == "subido"


def test_el_chat_busca_sin_filtro_de_servicio_ni_registrar_fuentes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    visto: dict[str, Any] = {}

    def buscar(vector: list[float], **kw: Any) -> list[Pasaje]:
        visto.update(kw)
        return [Pasaje(3, "guia-guardia.md", None, "escalar a nivel 2", 0.6, date(2026, 8, 1))]

    monkeypatch.setattr(conocimiento, "embed_consulta", lambda q: [0.0])
    monkeypatch.setattr("rag.store.buscar", buscar)
    monkeypatch.setattr(conocimiento, "_caido_hasta", 0.0)
    salida = chat.buscar_conocimiento("como se escala?")
    assert visto["servicio"] is None and "excluir_tipos" not in visto  # incluye runbooks
    assert "[C3] guia-guardia.md" in salida and "INFORMATIVO" in salida


def test_el_chat_sigue_si_el_conocimiento_falla(monkeypatch: pytest.MonkeyPatch) -> None:
    def cae(q: str) -> list[float]:
        raise RuntimeError("sin red")

    monkeypatch.setattr(conocimiento, "embed_consulta", cae)
    monkeypatch.setattr(conocimiento, "_caido_hasta", 0.0)
    assert chat.buscar_conocimiento("x") == conocimiento.NO_DISPONIBLE
