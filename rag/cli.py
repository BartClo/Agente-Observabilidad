"""CLI del conocimiento. Uso:

    python -m rag.cli listar
    python -m rag.cli borrar <id>

(`indexar` y `calibrar` se agregan en las tareas siguientes del plan.)
"""

from __future__ import annotations

import argparse

from rag import store


def _cmd_listar(_: argparse.Namespace) -> None:
    for d in store.listar_documentos():
        print(f"{d['id']:>4}  {d['origen']:<6}  {d['tipo']:<12}  {d['nombre']}  {d['servicios']}")


def _cmd_borrar(args: argparse.Namespace) -> None:
    store.borrar_documento(args.id)
    print(f"OK: documento {args.id} borrado.")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m rag.cli")
    sub = parser.add_subparsers(required=True)
    sub.add_parser("listar").set_defaults(func=_cmd_listar)
    p_borrar = sub.add_parser("borrar")
    p_borrar.add_argument("id", type=int)
    p_borrar.set_defaults(func=_cmd_borrar)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
