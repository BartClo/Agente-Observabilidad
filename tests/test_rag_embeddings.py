"""Embeddings con Gemini: la API se simula; no hay red ni key real."""

from __future__ import annotations

import math
import time
from typing import Any

import pytest

from rag import embeddings as emb


def _falso(valores: list[float]) -> tuple[Any, list[tuple[str, dict[str, Any], str]]]:
    llamadas: list[tuple[str, dict[str, Any], str]] = []

    def post(url: str, cuerpo: dict[str, Any], key: str) -> dict[str, Any]:
        llamadas.append((url, cuerpo, key))
        return {"embeddings": [{"values": valores} for _ in cuerpo["requests"]]}

    return post, llamadas


def test_normaliza_y_distingue_tipo_de_tarea(monkeypatch: pytest.MonkeyPatch) -> None:
    post, llamadas = _falso([3.0, 4.0] + [0.0] * (emb.EMBEDDING_DIM - 2))
    monkeypatch.setattr(emb, "_post", post)
    monkeypatch.setattr(emb, "_key", lambda: "k")
    (v,) = emb.embed_documentos(["hola"])
    assert math.isclose(math.sqrt(sum(x * x for x in v)), 1.0, rel_tol=1e-9)
    emb.embed_consulta("q")
    tareas = [c[1]["requests"][0]["taskType"] for c in llamadas]
    assert tareas == ["RETRIEVAL_DOCUMENT", "RETRIEVAL_QUERY"]
    assert llamadas[0][1]["requests"][0]["outputDimensionality"] == emb.EMBEDDING_DIM


def test_lotes_de_100(monkeypatch: pytest.MonkeyPatch) -> None:
    post, llamadas = _falso([1.0] + [0.0] * (emb.EMBEDDING_DIM - 1))
    monkeypatch.setattr(emb, "_post", post)
    monkeypatch.setattr(emb, "_key", lambda: "k")
    assert len(emb.embed_documentos(["x"] * 250)) == 250
    assert len(llamadas) == 3


def test_sin_textos_no_llama_a_la_api(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(emb, "_key", lambda: pytest.fail("no debe pedir la key"))
    assert emb.embed_documentos([]) == []


def test_reintenta_y_luego_falla_sin_filtrar_la_key(monkeypatch: pytest.MonkeyPatch) -> None:
    intentos = {"n": 0}

    def post(url: str, cuerpo: dict[str, Any], key: str) -> dict[str, Any]:
        intentos["n"] += 1
        raise OSError(f"boom {key}")

    monkeypatch.setattr(emb, "_post", post)
    monkeypatch.setattr(emb, "_key", lambda: "SECRETA")
    monkeypatch.setattr(time, "sleep", lambda s: None)
    with pytest.raises(emb.ErrorEmbeddings) as e:
        emb.embed_consulta("q")
    assert intentos["n"] == 3
    assert "SECRETA" not in str(e.value)
    assert e.value.__cause__ is None


def test_sin_key_da_error_claro(monkeypatch: pytest.MonkeyPatch) -> None:
    from infra.llm_config import ConfigLLMError

    def sin_key(proveedor: str, database_url: str | None = None) -> str:
        raise ConfigLLMError("no hay API key cargada para google")

    monkeypatch.setattr("infra.llm_config.api_key", sin_key)
    with pytest.raises(emb.ErrorEmbeddings, match="no hay API key"):
        emb.embed_consulta("q")
