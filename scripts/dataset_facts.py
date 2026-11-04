"""Dataset-wide facts cited in NOTES.md, computed from the catalog. Writes results/dataset_facts.json."""

from __future__ import annotations

import json
from pathlib import Path

from tmseeg_access.catalog import default_path, query
from tmseeg_access.config import resolve_data_root

OUTPUT = Path(__file__).resolve().parents[1] / "results" / "dataset_facts.json"
SITES = ["control", "parietal", "prefrontal", "premotor"]


def main() -> None:
    root = resolve_data_root()
    catalog = default_path(root)

    def rows(sql: str) -> list[dict]:
        return query(catalog, sql).to_dict(orient="records")

    subjects = query(catalog, "SELECT subject FROM participants")["subject"].tolist()
    present = query(
        catalog,
        "SELECT subject, acquisition FROM recordings WHERE task = 'tmseeg'",
    )
    have = set(zip(present["subject"], present["acquisition"], strict=True))
    missing = {s: [a for a in SITES if (s, a) not in have] for s in subjects}
    facts = {
        "subjects": len(subjects),
        "recordings": rows("SELECT task, count(*) AS n FROM recordings GROUP BY 1 ORDER BY 1"),
        "tmseeg_runs_expected_if_every_subject_had_all_4_sites": len(subjects) * 4,
        "tmseeg_runs_present": len(present),
        "tmseeg_runs_missing_by_subject": {s: m for s, m in missing.items() if m},
        "pulse_markers_indexed": int(query(catalog, "SELECT count(*) AS n FROM pulses")["n"][0]),
        "pulse_markers_flagged_duplicate": int(
            query(catalog, "SELECT sum(is_duplicate::INT) AS n FROM pulses")["n"][0]
        ),
        "channels_declared_in_tmseeg_sidecars": rows(
            "SELECT channels_sidecar AS channels, count(*) AS runs FROM recordings "
            "WHERE task = 'tmseeg' GROUP BY 1 ORDER BY 1"
        ),
        "tmseeg_runs_by_marker_count_top": rows(
            "SELECT pulse_count AS markers, count(*) AS runs FROM recordings "
            "WHERE task = 'tmseeg' GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT 6"
        ),
        "largest_marker_count_runs": rows(
            "SELECT recording_id, pulse_count AS markers FROM recordings "
            "WHERE task = 'tmseeg' ORDER BY pulse_count DESC, recording_id LIMIT 3"
        ),
        "release_files": rows(
            "SELECT local, count(*) AS files, sum(size_bytes)::BIGINT AS bytes "
            "FROM files GROUP BY 1 ORDER BY 1"
        ),
    }
    OUTPUT.write_text(json.dumps(facts, indent=2, default=int) + "\n", encoding="utf-8")
    print(json.dumps(facts, indent=2, default=int))


if __name__ == "__main__":
    main()
