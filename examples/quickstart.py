"""From a local copy of ds008037 to clean epochs around TMS pulses for one subject.

Run:  uv run python examples/quickstart.py
Needs TMSEEG_DATA_ROOT set, text metadata for the dataset, and sub-001's TMS signal:

    tmseeg-access download --tier metadata
    tmseeg-access download --tier signal --subjects sub-001 --tasks tmseeg
    tmseeg-access catalog

Prints each step and saves the numbers to results/quickstart.json.
"""

from __future__ import annotations

import json
import statistics
import time
from pathlib import Path

from tmseeg_access.catalog import default_path, query
from tmseeg_access.dataset import Dataset, DuplicatePulseError

SUBJECT = "sub-001"
SITE = "parietal"
OUTPUT = Path(__file__).resolve().parents[1] / "results" / "quickstart.json"


def timed(function, *args, **kwargs):
    started = time.perf_counter()
    value = function(*args, **kwargs)
    return value, time.perf_counter() - started


def median_ms(function, repeats: int = 7) -> float:
    return round(statistics.median(timed(function)[1] for _ in range(repeats)) * 1000, 2)


def main() -> None:
    out: dict = {"subject": SUBJECT, "site": SITE}

    print("1. Open the dataset")
    ds = Dataset()
    out["subjects"] = len(ds.subjects())
    print(f"   {ds}")
    print(f"   sessions({SUBJECT}) = {ds.sessions(SUBJECT)} (this dataset has no session level)")

    print("2. What exists for this subject?")
    recordings = ds.recordings(SUBJECT)
    out["recordings_for_subject"] = len(recordings)
    print(recordings.to_string(index=False))

    print("3. Metadata: recordings joined to participant and behavioural fields")
    meta = ds.metadata()
    out["metadata_shape"] = list(meta.shape)
    row = meta[(meta.subject == SUBJECT) & (meta.acquisition == SITE)].iloc[0]
    fields = ["age", "sex", "pulse_count", "channels_sidecar", "nback_accuracy"]
    out["metadata_row"] = {
        name: row[name].item() if hasattr(row[name], "item") else row[name] for name in fields
    }
    print(
        f"   {meta.shape[0]} rows, {meta.shape[1]} columns. {SUBJECT} {SITE}: {out['metadata_row']}"
    )

    print("4. Open the recording. Lazy: no signal is read yet")
    raw, first = timed(ds.load_raw, SUBJECT, acquisition=SITE)
    _, second = timed(ds.load_raw, SUBJECT, acquisition=SITE)
    out["load_raw_ms"] = {"first": round(first * 1000, 1), "repeat": round(second * 1000, 2)}
    out["raw"] = {
        "channels": len(raw.ch_names),
        "sampling_rate_hz": raw.info["sfreq"],
        "duration_s": round(raw.duration, 3),
        "data_in_memory": raw.preload,
    }
    print(f"   {raw}")
    print(
        f"   first open {out['load_raw_ms']['first']} ms, repeat {out['load_raw_ms']['repeat']} ms"
    )

    print("5. Pulses, as published, with spacing")
    pulses = ds.pulses(SUBJECT, SITE)
    gaps = pulses["gap_from_previous_s"].dropna()
    out["pulses"] = {
        "count": len(pulses),
        "suspected_duplicates": int(pulses["is_duplicate"].sum()),
        "gap_min_s": round(float(gaps.min()), 3),
        "gap_median_s": round(float(gaps.median()), 3),
        "gap_max_s": round(float(gaps.max()), 3),
    }
    print(f"   {out['pulses']}")

    print("6. Epochs around each pulse")
    epochs, first = timed(
        ds.epochs_around_pulses, SUBJECT, SITE, tmin=-0.1, tmax=0.5, baseline=(-0.1, -0.01)
    )
    _, second = timed(
        ds.epochs_around_pulses, SUBJECT, SITE, tmin=-0.1, tmax=0.5, baseline=(-0.1, -0.01)
    )
    out["epochs"] = {
        "shape": list(epochs.get_data().shape),
        "first_ms": round(first * 1000, 1),
        "repeat_ms": round(second * 1000, 1),
        "provenance": json.loads(epochs.info["description"]),
    }
    print(f"   {epochs}")
    print(f"   first {out['epochs']['first_ms']} ms, repeat {out['epochs']['repeat_ms']} ms")
    print(f"   provenance: {epochs.info['description']}")
    print(epochs.metadata.head(3).to_string(index=False))

    print("7. Ambiguous pulses stop the analysis rather than passing through silently")
    try:
        ds.epochs_around_pulses("sub-136", "parietal")
    except DuplicatePulseError as error:
        out["refused_example"] = str(error)
        print(f"   DuplicatePulseError: {error}")

    print("8. Ask the catalog with SQL")
    catalog = default_path(ds.root)
    sql = (
        "SELECT acquisition, count(*) AS runs, sum(pulse_count)::BIGINT AS markers, "
        "count(*) FILTER (pulse_count <> 120) AS runs_not_120 "
        "FROM recordings WHERE task = 'tmseeg' GROUP BY 1 ORDER BY 1"
    )
    table = query(catalog, sql)
    print(table.to_string(index=False))
    out["catalog_by_site"] = table.to_dict(orient="records")
    out["catalog_query_median_ms"] = median_ms(lambda: query(catalog, sql))
    print(f"   median query time {out['catalog_query_median_ms']} ms, including opening the file")

    OUTPUT.parent.mkdir(exist_ok=True)
    OUTPUT.write_text(json.dumps(out, indent=2, default=int) + "\n", encoding="utf-8")
    print(f"Saved {OUTPUT.name}")


if __name__ == "__main__":
    main()
