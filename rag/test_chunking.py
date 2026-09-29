import pytest

from rag.chunking import chunk_text


def test_empty_text_returns_no_chunks() -> None:
    assert chunk_text("", source="f.txt") == []


def test_short_text_returns_single_chunk() -> None:
    chunks = chunk_text("hola mundo", source="f.txt", size=100, overlap=10)
    assert len(chunks) == 1
    assert chunks[0].content == "hola mundo"
    assert chunks[0].source == "f.txt"


def test_long_text_overlaps_between_chunks() -> None:
    text = "a" * 25
    chunks = chunk_text(text, source="f.txt", size=10, overlap=4)
    assert len(chunks) > 1
    assert all(c.source == "f.txt" for c in chunks)
    assert "".join(c.content[0] for c in chunks) == "a" * len(chunks)


def test_size_must_be_greater_than_overlap() -> None:
    with pytest.raises(ValueError):
        chunk_text("algo", source="f.txt", size=10, overlap=10)
