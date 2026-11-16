"""Subir, listar y borrar documentos del conocimiento (RAG) desde la UI: solo admin."""

from __future__ import annotations

import base64
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api import app

ADMIN = {"Authorization": "Bearer admin-token"}


@pytest.fixture
def c(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("AIOPS_API_TOKEN", "op-token")
    monkeypatch.setenv("AIOPS_ADMIN_TOKEN", "admin-token")
    return TestClient(app)


@pytest.fixture
def indexados(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    from rag import ingest, store

    hechos: list[Any] = []

    def indexar(doc: Any, paginas: Any) -> int:
        hechos.append(doc)
        return 7

    monkeypatch.setattr(ingest, "indexar", indexar)
    monkeypatch.setattr(store, "listar_documentos", lambda: [{"id": 7, "nombre": "ficha.md"}])
    monkeypatch.setattr(store, "borrar_documento", lambda i: hechos.append(("borrado", i)))
    return hechos


def _b64(texto: str) -> str:
    return base64.b64encode(texto.encode()).decode()


def test_solo_admin(c: TestClient, indexados: list[Any]) -> None:
    op = {"Authorization": "Bearer op-token"}
    assert c.get("/conocimiento", headers=op).status_code in (401, 403)
    assert c.post("/conocimiento", headers=op, json={}).status_code in (401, 403)
    assert c.delete("/conocimiento/7", headers=op).status_code in (401, 403)
    assert indexados == []


def test_subir_listar_y_borrar(c: TestClient, indexados: list[Any]) -> None:
    cuerpo = {"nombre": "../../etc/ficha.md", "contenido_b64": _b64("# Ficha\n\ntexto util")}
    r = c.post("/conocimiento", headers=ADMIN, json=cuerpo)
    assert r.status_code == 200, r.text
    assert r.json() == {"id": 7, "nombre": "ficha.md"}  # sin ruta: solo el nombre
    assert indexados[0].nombre == "ficha.md" and indexados[0].origen == "subido"
    assert c.get("/conocimiento", headers=ADMIN).json() == [{"id": 7, "nombre": "ficha.md"}]
    assert c.delete("/conocimiento/7", headers=ADMIN).json() == {"ok": True}
    assert ("borrado", 7) in indexados


@pytest.mark.parametrize(
    ("cuerpo", "codigo"),
    [
        ({"nombre": "x.exe", "contenido_b64": _b64("a")}, 422),
        ({"nombre": "x.md", "contenido_b64": "no es base64!"}, 422),
        ({"nombre": "x.md"}, 422),
        ({"nombre": "x.pdf", "contenido_b64": _b64("no soy un pdf")}, 422),
    ],
)
def test_rechaza_lo_invalido(
    c: TestClient, indexados: list[Any], cuerpo: dict[str, str], codigo: int
) -> None:
    assert c.post("/conocimiento", headers=ADMIN, json=cuerpo).status_code == codigo
    assert indexados == []


def test_la_ui_tiene_la_seccion_de_conocimiento(c: TestClient) -> None:
    html = c.get("/ui").text
    assert 'id="sec-rag"' in html and 'id="rag-subir"' in html and "/conocimiento" in html
