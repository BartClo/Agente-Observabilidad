"""CLI del conocimiento. Uso:

    python -m rag.cli indexar <archivo|carpeta> [--origen repo|subido] [--tipo TIPO]
    python -m rag.cli listar
    python -m rag.cli calibrar [corpus/calibracion.json]
    python -m rag.cli borrar <id>

`indexar` lee .md y .pdf; usa la key de Gemini cargada (cifrada) desde la UI.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from rag import ingest, store
from rag.types import Documento

SUFIJOS = {".md", ".pdf"}


def _leer(archivo: Path, nombre: str, origen: str, tipo: str) -> tuple[Documento, ingest.Paginas]:
    if archivo.suffix == ".pdf":
        return ingest.leer_pdf(archivo.read_bytes(), nombre, tipo=tipo)
    return ingest.leer_markdown(archivo.read_text(encoding="utf-8"), nombre, origen, tipo)


def indexar_ruta(ruta: Path, origen: str = "repo", tipo: str = "otro") -> list[tuple[str, int]]:
    """Indexa un archivo o los .md/.pdf bajo una carpeta. Devuelve (nombre, documento_id)."""
    if ruta.is_file():
        archivos = [ruta]
    else:
        archivos = sorted(p for p in ruta.rglob("*") if p.suffix in SUFIJOS)
    resultado: list[tuple[str, int]] = []
    for archivo in archivos:
        doc, paginas = _leer(archivo, archivo.name, origen, tipo)
        resultado.append((archivo.name, ingest.indexar(doc, paginas)))
    return resultado


def _cmd_indexar(args: argparse.Namespace) -> None:
    for nombre, doc_id in indexar_ruta(Path(args.ruta), args.origen, args.tipo):
        print(f"OK  {doc_id:>4}  {nombre}")


def _cmd_calibrar(args: argparse.Namespace) -> None:
    from rag import calibracion

    print(calibracion.informe(Path(args.ruta)))


def _cmd_listar(_: argparse.Namespace) -> None:
    for d in store.listar_documentos():
        print(f"{d['id']:>4}  {d['origen']:<6}  {d['tipo']:<12}  {d['nombre']}  {d['servicios']}")


def _cmd_borrar(args: argparse.Namespace) -> None:
    store.borrar_documento(args.id)
    print(f"OK: documento {args.id} borrado.")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m rag.cli")
    sub = parser.add_subparsers(required=True)
    p_indexar = sub.add_parser("indexar")
    p_indexar.add_argument("ruta")
    p_indexar.add_argument("--origen", choices=["repo", "subido"], default="repo")
    p_indexar.add_argument("--tipo", default="otro", help="tipo si el archivo no lo declara")
    p_indexar.set_defaults(func=_cmd_indexar)
    sub.add_parser("listar").set_defaults(func=_cmd_listar)
    p_cal = sub.add_parser("calibrar")
    p_cal.add_argument("ruta", nargs="?", default="corpus/calibracion.json")
    p_cal.set_defaults(func=_cmd_calibrar)
    p_borrar = sub.add_parser("borrar")
    p_borrar.add_argument("id", type=int)
    p_borrar.set_defaults(func=_cmd_borrar)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
