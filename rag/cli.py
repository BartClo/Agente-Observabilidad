"""CLI para probar el componente RAG sin correr un agente. Uso:

    python -m rag.cli init-db
    python -m rag.cli ingest <collection> <path> [--tenant TENANT]
    python -m rag.cli query <collection> "<texto>" [--k K] [--tenant TENANT]

Tambien expuesto como `make rag-init-db`, `make rag-ingest`, `make rag-query`.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from rag import ingest, retrieve, store


def _cmd_init_db(_: argparse.Namespace) -> None:
    store.init_db()
    print("OK: tabla rag_chunks lista.")


def _cmd_ingest(args: argparse.Namespace) -> None:
    count = ingest.ingest_path(args.collection, Path(args.path), tenant_id=args.tenant)
    print(f"OK: {count} chunks guardados en collection={args.collection!r} tenant={args.tenant!r}")


def _cmd_query(args: argparse.Namespace) -> None:
    results = retrieve.search(args.collection, args.text, k=args.k, tenant_id=args.tenant)
    if not results:
        print("Sin resultados.")
        return
    for i, r in enumerate(results, start=1):
        print(f"\n[{i}] distancia={r.distance:.4f} fuente={r.source}")
        print(r.content)


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m rag.cli")
    sub = parser.add_subparsers(required=True)

    sub.add_parser("init-db").set_defaults(func=_cmd_init_db)

    p_ingest = sub.add_parser("ingest")
    p_ingest.add_argument("collection")
    p_ingest.add_argument("path")
    p_ingest.add_argument("--tenant", default="default")
    p_ingest.set_defaults(func=_cmd_ingest)

    p_query = sub.add_parser("query")
    p_query.add_argument("collection")
    p_query.add_argument("text")
    p_query.add_argument("--k", type=int, default=4)
    p_query.add_argument("--tenant", default=None)
    p_query.set_defaults(func=_cmd_query)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
