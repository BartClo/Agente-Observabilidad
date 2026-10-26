"""Lectura e indexado de documentos: Markdown (con metadatos en el encabezado) y PDF.

Un documento es DATO no confiable: los secretos se enmascaran antes de embeber (asi no
viajan a Google ni al LLM) y el PDF se valida (cabecera, tamano, paginas, texto).
"""

from __future__ import annotations

import hashlib
import io
from collections.abc import Callable
from datetime import date

from domain.aiops_core.saneamiento import enmascarar
from rag import embeddings, store
from rag.chunking import fragmentar
from rag.types import Documento

MAX_PDF_BYTES = 5 * 1024 * 1024
MAX_PAGINAS = 200
Paginas = list[tuple[int | None, str]]


class ErrorIngesta(ValueError):
    """El documento no se puede indexar; el mensaje es apto para mostrarlo al usuario."""


def _sha(datos: bytes) -> str:
    return hashlib.sha256(datos).hexdigest()


def _separar_encabezado(texto: str) -> tuple[dict[str, str], str]:
    """Front matter `---\\nclave: valor\\n---` al inicio. Sin encabezado: ({}, texto)."""
    if not texto.startswith("---\n"):
        return {}, texto
    fin = texto.find("\n---", 4)
    if fin == -1:
        return {}, texto
    meta: dict[str, str] = {}
    for linea in texto[4:fin].splitlines():
        clave, sep, valor = linea.partition(":")
        if sep:
            meta[clave.strip()] = valor.strip()
    return meta, texto[fin + 4 :].lstrip("\n")


def leer_markdown(texto: str, nombre: str, origen: str = "repo") -> tuple[Documento, Paginas]:
    meta, cuerpo = _separar_encabezado(texto)
    try:
        vigente = date.fromisoformat(meta["vigente_desde"]) if "vigente_desde" in meta else None
    except ValueError as exc:
        raise ErrorIngesta(f"{nombre}: vigente_desde no es una fecha ISO") from exc
    servicios = tuple(s.strip() for s in meta.get("servicios", "").split(",") if s.strip())
    datos = texto.encode()
    doc = Documento(
        nombre=nombre,
        origen=origen,
        servicios=servicios,
        tipo=meta.get("tipo", "otro"),
        vigente_desde=vigente,
        obsoleto=meta.get("obsoleto", "false").lower() == "true",
        sha256=_sha(datos),
        paginas=None,
        bytes_=len(datos),
        subido_por=None,
    )
    return doc, [(None, cuerpo)]


def leer_pdf(
    datos: bytes,
    nombre: str,
    *,
    servicios: tuple[str, ...] = (),
    tipo: str = "otro",
    subido_por: str | None = None,
) -> tuple[Documento, Paginas]:
    if len(datos) > MAX_PDF_BYTES:
        raise ErrorIngesta(f"el PDF supera {MAX_PDF_BYTES // (1024 * 1024)} MB")
    if not datos.startswith(b"%PDF-"):
        raise ErrorIngesta("el archivo no es un PDF")
    from pypdf import PdfReader

    try:
        lector = PdfReader(io.BytesIO(datos))
        if lector.is_encrypted:
            raise ErrorIngesta("el PDF esta cifrado")
        if len(lector.pages) > MAX_PAGINAS:
            raise ErrorIngesta(f"el PDF tiene mas de {MAX_PAGINAS} paginas")
        paginas: Paginas = [(n, p.extract_text() or "") for n, p in enumerate(lector.pages, 1)]
    except ErrorIngesta:
        raise
    except Exception as exc:  # pypdf lanza muchos tipos ante un PDF danado
        raise ErrorIngesta("no se pudo leer el PDF") from exc
    if not any(t.strip() for _, t in paginas):
        raise ErrorIngesta("el PDF no tiene texto extraible (escaneado?)")
    doc = Documento(
        nombre=nombre,
        origen="subido",
        servicios=servicios,
        tipo=tipo,
        vigente_desde=None,
        obsoleto=False,
        sha256=_sha(datos),
        paginas=len(paginas),
        bytes_=len(datos),
        subido_por=subido_por,
    )
    return doc, paginas


def indexar(
    doc: Documento,
    paginas: Paginas,
    embed: Callable[[list[str]], list[list[float]]] = embeddings.embed_documentos,
) -> int:
    """Devuelve el id del documento. Si el mismo contenido ya esta indexado no llama al
    embedder (no gasta API ni duplica)."""
    previo = store.existe_sha(doc.sha256)
    if previo is not None:
        return previo
    fragmentos = fragmentar([(n, enmascarar(t)) for n, t in paginas])
    if not fragmentos:
        raise ErrorIngesta(f"{doc.nombre}: no tiene texto para indexar")
    vectores = embed([f.contenido for f in fragmentos])
    return store.guardar_documento(doc, fragmentos, vectores)
