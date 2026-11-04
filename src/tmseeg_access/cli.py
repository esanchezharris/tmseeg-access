"""Command line entry point: ``tmseeg-access <command>``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

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


def _check(args: argparse.Namespace) -> int:
    from tmseeg_access.catalog import default_path, store_issues
    from tmseeg_access.checks import run_all
    from tmseeg_access.dataset import Dataset

    ds = Dataset(args.data_root)
    issues, extra = run_all(ds)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    issues.to_csv(output / "issues.csv", index=False)
    (output / "check_summary.json").write_text(
        json.dumps(
            {
                "coverage": extra["coverage"],
                "issues_total": len(issues),
                "issues_by_rule": issues.groupby("rule").size().to_dict(),
                "issues_by_severity": issues.groupby("severity").size().to_dict(),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    pd.DataFrame(extra["artifact"]).to_csv(output / "pulse_artifact.csv", index=False)
    if default_path(ds.root).exists():
        store_issues(default_path(ds.root), issues)
    print(f"{len(issues)} issues written to {output}")
    print(issues.groupby(["severity", "rule"]).size().to_string())
    return 0


def _report(args: argparse.Namespace) -> int:
    from tmseeg_access.catalog import default_path
    from tmseeg_access.report import load_inputs, write_report

    root = resolve_data_root(args.data_root)
    inputs = load_inputs(Path(args.catalog or default_path(root)), Path(args.results))
    print(write_report(inputs, Path(args.output)))
    return 0


def _deidentify(args: argparse.Namespace) -> int:
    from tmseeg_access.deidentify import deidentify

    log = deidentify(
        resolve_data_root(args.data_root),
        args.output,
        subjects=args.subjects,
        drop_participant_columns=args.drop_participant_columns,
        drop_head_geometry=args.drop_head_geometry,
        include_signal=not args.no_signal,
    )
    print(json.dumps(log, indent=2))
    return 0


def _export(args: argparse.Namespace) -> int:
    from tmseeg_access.dataset import Dataset
    from tmseeg_access.matlab import export_epochs_mat, export_epochs_set, export_metadata

    ds = Dataset(args.data_root)
    epochs = ds.epochs_around_pulses(
        args.subject,
        args.site,
        tmin=args.tmin,
        tmax=args.tmax,
        on_duplicate=args.on_duplicate,
        exclude_channels=args.exclude_channels,
    )
    stem = Path(args.output) / f"{args.subject}_{args.site}_epochs"
    stem.parent.mkdir(parents=True, exist_ok=True)
    written = []
    if "mat" in args.formats:
        written.append(export_epochs_mat(epochs, stem.with_suffix(".mat")))
    if "set" in args.formats:
        written.append(export_epochs_set(epochs, stem.with_suffix(".set")))
    if args.metadata:
        written.append(export_metadata(ds.metadata(), Path(args.output) / "metadata.mat"))
    print("\n".join(str(path) for path in written))
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

    chk = sub.add_parser("check", help="Run the data quality checks. Never changes the data.")
    chk.add_argument("--data-root", help=ROOT_HELP)
    chk.add_argument("--output", default="results", help="Folder for issues.csv and summaries.")
    chk.set_defaults(func=_check)

    rep = sub.add_parser("report", help="Write the HTML report and CSVs from saved results.")
    rep.add_argument("--data-root", help=ROOT_HELP)
    rep.add_argument("--catalog", help="Catalog file. Defaults to the derivatives folder.")
    rep.add_argument("--results", default="results", help="Folder holding the check outputs.")
    rep.add_argument("--output", default="results/report", help="Folder for the report.")
    rep.set_defaults(func=_report)

    dei = sub.add_parser(
        "deidentify", help="Write a de-identified copy. Not a HIPAA certification."
    )
    dei.add_argument("--output", required=True, help="New folder, outside the dataset.")
    dei.add_argument("--data-root", help=ROOT_HELP)
    dei.add_argument("--subjects", nargs="+", help="Copy only these subjects.")
    dei.add_argument("--drop-participant-columns", nargs="+", default=[])
    dei.add_argument("--drop-head-geometry", action="store_true")
    dei.add_argument("--no-signal", action="store_true", help="Leave out the .fdt signal files.")
    dei.set_defaults(func=_deidentify)

    exp = sub.add_parser("export", help="Export epochs for MATLAB as .mat and EEGLAB .set.")
    exp.add_argument("--subject", required=True)
    exp.add_argument("--site", required=True)
    exp.add_argument("--output", required=True, help="Folder for the exported files.")
    exp.add_argument("--data-root", help=ROOT_HELP)
    exp.add_argument("--formats", nargs="+", choices=["mat", "set"], default=["mat", "set"])
    exp.add_argument("--tmin", type=float, default=-0.1)
    exp.add_argument("--tmax", type=float, default=0.5)
    exp.add_argument("--on-duplicate", choices=["error", "keep_first"], default="error")
    exp.add_argument("--exclude-channels", nargs="+", default=[])
    exp.add_argument("--metadata", action="store_true", help="Also export the metadata table.")
    exp.set_defaults(func=_export)

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
