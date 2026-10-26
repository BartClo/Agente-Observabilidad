"""Congelar el agente: el experimento final solo corre sobre el codigo y el modelo que se
registraron, y sin modelo de respaldo (un incidente atendido por dos modelos no es
atribuible a ninguno)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scripts import congelar, experimento

CFG_OK: dict[str, Any] = {
    "activo": {"proveedor": "deepseek", "modelo": "deepseek-chat"},
    "respaldo": {"proveedor": None, "modelo": None},
}


def _git_falso(commit: str = "abc123", sucio: str = "") -> Any:
    def git(*args: str) -> str:
        return sucio if args[:2] == ("status", "--porcelain") else commit

    return git


def test_registro_con_todo_lo_que_hace_reproducible_la_corrida(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(congelar, "_git", _git_falso())
    monkeypatch.setattr(congelar, "_config_llm", lambda: CFG_OK)
    registro = congelar.construir_registro()
    assert registro["commit"] == "abc123" and registro["modelo"] == "deepseek:deepseek-chat"
    assert registro["agente"] == "unico" and len(str(registro["prompt_sha256"])) == 64
    assert len(str(registro["runbooks_sha256"])) == 64


@pytest.mark.parametrize(
    ("git", "cfg", "mensaje"),
    [
        (_git_falso(sucio=" M agents/aiops/prompt.md"), CFG_OK, "sin commitear"),
        (
            _git_falso(),
            {**CFG_OK, "respaldo": {"proveedor": "google", "modelo": "gemini-x"}},
            "respaldo",
        ),
        (
            _git_falso(),
            {**CFG_OK, "activo": {"proveedor": None, "modelo": None}},
            "modelo elegido",
        ),
    ],
)
def test_se_niega_a_congelar_si_algo_no_es_atribuible(
    monkeypatch: pytest.MonkeyPatch, git: Any, cfg: dict[str, Any], mensaje: str
) -> None:
    monkeypatch.setattr(congelar, "_git", git)
    monkeypatch.setattr(congelar, "_config_llm", lambda: cfg)
    with pytest.raises(SystemExit, match=mensaje):
        congelar.construir_registro()


def test_la_fase_final_exige_el_congelado_y_que_el_codigo_no_haya_cambiado(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(experimento, "RAIZ", tmp_path)
    with pytest.raises(SystemExit, match="congelar"):
        experimento.exigir_congelado()  # no hay congelado.json

    (tmp_path / "resultados").mkdir()
    (tmp_path / "resultados" / "congelado.json").write_text(
        json.dumps({"commit": "abc123"}), encoding="utf-8"
    )

    def git_ok(*args: str) -> str:
        return "" if args[0] == "status" else "abc123"

    monkeypatch.setattr(experimento, "_git_salida", git_ok)
    experimento.exigir_congelado()  # mismo commit y arbol limpio: no lanza

    monkeypatch.setattr(experimento, "_git_salida", lambda *a: "" if a[0] == "status" else "otro")
    with pytest.raises(SystemExit, match="cambio despues de congelar"):
        experimento.exigir_congelado()

    monkeypatch.setattr(
        experimento, "_git_salida", lambda *a: " M x.py" if a[0] == "status" else "abc123"
    )
    with pytest.raises(SystemExit, match="sin commitear"):
        experimento.exigir_congelado()


def test_el_registro_congela_el_rag_y_el_corpus(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(congelar, "_git", _git_falso())
    monkeypatch.setattr(congelar, "_config_llm", lambda: CFG_OK)
    rag = congelar.construir_registro()["rag"]
    assert isinstance(rag, dict)
    assert rag["activo"] == "1" and rag["embedding_modelo"] == "gemini-embedding-001"
    assert len(str(rag["corpus_sha256"])) == 64
    assert rag["config"]["AIOPS_RAG_ORIGENES"] == "repo"
