"""Command line entry point: ``tmseeg-access <command>``."""

from __future__ import annotations

import argparse
import json
import sys

from tmseeg_access.config import DATASET, TAG, resolve_data_root

ROOT_HELP = "Dataset folder. Defaults to TMSEEG_DATA_ROOT."


def _download(args: argparse.Namespace) -> int:
    from tmseeg_access import download as dl

    root = resolve_data_root(args.data_root)
    cached = dl.manifest_path(root, args.tag)
    if cached.exists():
        manifest = dl.load_manifest(cached)
    else:
        manifest = dl.fetch_manifest(args.dataset, args.tag)
        dl.save_manifest(manifest, cached)
    files = dl.select_files(manifest, args.tier, args.subjects, args.tasks)
    summary = dl.download_files(files, root, workers=args.workers)
    summary.update(tier=args.tier, dataset=args.dataset, tag=args.tag)
    print(json.dumps(summary, indent=2))
    return 1 if summary["failed"] else 0


def _catalog(args: argparse.Namespace) -> int:
    from tmseeg_access.catalog import build_catalog
    from tmseeg_access.dataset import Dataset

    print(json.dumps(build_catalog(Dataset(args.data_root), args.output), indent=2))
    return 0


def _query(args: argparse.Namespace) -> int:
    from tmseeg_access.catalog import default_path, query

    path = args.catalog or default_path(resolve_data_root(args.data_root))
    print(query(path, args.sql).to_string(index=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tmseeg-access", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    dl = sub.add_parser("download", help="Fetch a pinned snapshot and verify every file.")
    dl.add_argument("--data-root", help=ROOT_HELP)
    dl.add_argument("--tier", choices=["metadata", "headers", "signal"], default="metadata")
    dl.add_argument("--subjects", nargs="+", help="For example: sub-001 sub-005")
    dl.add_argument("--tasks", nargs="+", help="For example: tmseeg rest")
    dl.add_argument("--dataset", default=DATASET)
    dl.add_argument("--tag", default=TAG)
    dl.add_argument("--workers", type=int, default=8)
    dl.set_defaults(func=_download)

    cat = sub.add_parser("catalog", help="Build the DuckDB metadata catalog.")
    cat.add_argument("--data-root", help=ROOT_HELP)
    cat.add_argument("--output", help="Catalog file. Defaults to the derivatives folder.")
    cat.set_defaults(func=_catalog)

    qry = sub.add_parser("query", help="Run read-only SQL against the catalog.")
    qry.add_argument("sql")
    qry.add_argument("--data-root", help=ROOT_HELP)
    qry.add_argument("--catalog", help="Catalog file. Defaults to the derivatives folder.")
    qry.set_defaults(func=_query)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
