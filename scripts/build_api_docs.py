"""Generate docs/api.md from the package's docstrings, so the reference cannot drift from the code."""

from __future__ import annotations

import importlib
import inspect
from pathlib import Path

OUTPUT = Path(__file__).resolve().parents[1] / "docs" / "api.md"
MODULES = [
    ("tmseeg_access.dataset", ["Dataset", "DataNotLocalError", "DuplicatePulseError"]),
    ("tmseeg_access.catalog", ["build_catalog", "query", "store_issues", "read_set_header"]),
    ("tmseeg_access.checks.run", ["run_all"]),
    ("tmseeg_access.checks.issues", ["Issue", "issues_frame", "load_protocol"]),
    ("tmseeg_access.deidentify", ["deidentify", "scan_set_header"]),
    (
        "tmseeg_access.matlab",
        ["export_epochs_mat", "read_epochs_mat", "export_epochs_set", "export_metadata"],
    ),
    ("tmseeg_access.report", ["load_inputs", "write_report"]),
    ("tmseeg_access.download", ["fetch_manifest", "select_files", "download_files"]),
]


def signature(item) -> str:
    return str(inspect.signature(item)).replace("'", '"')


def describe_class(lines: list[str], item) -> None:
    for name, member in inspect.getmembers(item, inspect.isfunction):
        if name.startswith("_") and name != "__init__":
            continue
        doc = inspect.getdoc(member)
        lines += [f"#### `{item.__name__}.{name}{signature(member)}`", ""]
        if doc:
            lines += [doc, ""]


def main() -> None:
    lines = [
        "# API reference",
        "",
        "Generated from docstrings by `scripts/build_api_docs.py`.",
        "",
        "The command line tool is `tmseeg-access`. Run `tmseeg-access --help` for its commands.",
        "",
    ]
    for module_name, names in MODULES:
        module = importlib.import_module(module_name)
        lines += [f"## `{module_name}`", ""]
        if module.__doc__:
            lines += [inspect.cleandoc(module.__doc__), ""]
        for name in names:
            item = getattr(module, name)
            lines += [f"### `{name}`", ""]
            if inspect.isclass(item):
                doc = inspect.getdoc(item)
                if doc:
                    lines += [doc, ""]
                if not issubclass(item, Exception):
                    describe_class(lines, item)
            else:
                lines += [f"`{name}{signature(item)}`", ""]
                doc = inspect.getdoc(item)
                if doc:
                    lines += [doc, ""]
    OUTPUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {OUTPUT}")


if __name__ == "__main__":
    main()
