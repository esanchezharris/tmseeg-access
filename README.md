# tmseeg-access

Clean, fast access to a public TMS-EEG dataset and its metadata, with data quality checks, reporting
and MATLAB export.

Built around [OpenNeuro ds008037](https://openneuro.org/datasets/ds008037) (v1.0.1, CC0). It uses
public, de-identified data only.

- **Data access:** `Dataset` gives subjects, recordings, joined metadata, raw data, and epochs around
  TMS pulses. Reads are lazy and cached.
- **Metadata catalog:** a DuckDB file indexing every recording, pulse and file hash, so analysts can use
  SQL. See [example queries](docs/catalog_queries.md).
- **Quality checks:** pulse timing, channel and rate consistency, sidecars versus headers, and the signal.
  Each finding says what was observed, where, the rule, and a suggested action. Nothing is fixed
  or dropped silently.
- **Privacy:** a [de-identification step](docs/privacy.md) that works on a copy. It isn't a certification
  of HIPAA compliance.
- **MATLAB:** [export to `.mat` and EEGLAB `.set`](docs/matlab.md).
- **Reporting:** an HTML report and CSVs. See [`results/report/report.html`](results/report/report.html).

## Install

Needs [uv](https://docs.astral.sh/uv/). Versions are pinned in `uv.lock`.

```bash
uv sync
```

## Quickstart

Tell the package where the data should live. It can be anywhere, and it's the only place data goes.
On Windows PowerShell, use `$env:TMSEEG_DATA_ROOT = "E:\tms-eeg-data\ds008037"`.

```bash
export TMSEEG_DATA_ROOT=/path/to/ds008037
```

Download text metadata for every subject, plus one subject's TMS signal. Every file is checked against
the release's own hashes.

```bash
uv run tmseeg-access download --tier metadata
```

```bash
uv run tmseeg-access download --tier signal --subjects sub-001 --tasks tmseeg
```

Build the catalog and run the checks:

```bash
uv run tmseeg-access catalog
```

```bash
uv run tmseeg-access check
```

Then in Python:

```python
from tmseeg_access.dataset import Dataset

ds = Dataset()                                  # uses TMSEEG_DATA_ROOT
ds.subjects()                                   # every subject
ds.recordings("sub-001")                        # what exists, and what is local
meta = ds.metadata()                            # recordings + participants + behaviour

raw = ds.load_raw("sub-001", acquisition="parietal")   # lazy: reads no signal yet
ds.pulses("sub-001", "parietal")                # markers, spacing, duplicates flagged

epochs = ds.epochs_around_pulses(
    "sub-001", "parietal",
    tmin=-0.1, tmax=0.5,
    baseline=(-0.1, -0.01),
    exclude_channels=("TRIGGER",),
)
```

`examples/quickstart.py` runs this end to end. For the full walkthrough, see the
[tutorial notebook](docs/tutorial.ipynb).

## Commands

| Command | What it does |
|---|---|
| `download` | Fetch a pinned snapshot, verifying every file |
| `catalog` | Build the DuckDB catalog |
| `query "<sql>"` | Run read-only SQL against the catalog |
| `check` | Run the quality checks and write `issues.csv` |
| `report` | Write the HTML report and CSVs from saved results |
| `export` | Export epochs for MATLAB and EEGLAB |
| `deidentify` | Write a de-identified copy |

## Read this before analysing the data

- **Check the run first.** Some runs still contain a large TMS artifact, and their headers can't tell you
  which. Query the `issues` table, but signal rules only cover runs whose signal you downloaded.
- **Check trigger codes.** In some runs, markers flagged as pulses carry other codes. The rule
  `pulse.mixed_marker_codes` reports the codes and counts. Per-marker codes are only in the `.set` header,
  and all these markers are epoched.
- **Doubled pulses stop epoching.** Some runs have suspected doubled markers. `epochs_around_pulses` refuses
  them until you pass `on_duplicate="keep_first"`, and records that choice.
- **Exclude `TRIGGER`** from most TMS runs before average referencing. It's typed as EEG and usually flat.
- **Re-reference explicitly.** The sidecars state FCz, the preprint states FPz, and FCz carries signal in
  all 40 signal-checked runs.
- **Epochs here aren't analysis-ready.** They haven't been through a full TMS-EEG cleaning pipeline.

See [NOTES.md](NOTES.md) for what was found, how a pulse was identified and verified, and a plain-English
explanation of the science.

## Docs

[Tutorial](docs/tutorial.ipynb), [API reference](docs/api.md), [catalog queries](docs/catalog_queries.md),
[privacy](docs/privacy.md), [MATLAB](docs/matlab.md), [changelog](CHANGELOG.md), [audit](AUDIT.md).

## Tests

```bash
uv run pytest
```

Tests use small synthetic fixtures. Tests on real data skip unless `TMSEEG_DATA_ROOT` is set. CI runs
the synthetic tests only.

`scripts/rebuild_evidence.py` rebuilds the catalog, checks, report, evidence files and generated docs. It
adds the Octave and EEGLAB test when `OCTAVE_CLI` and `EEGLAB_PATH` are set.

## Limits

Signal checks are only as complete as your download. A check that couldn't run is reported as coverage,
not as a pass. The package is built for this dataset's layout, and supporting another would take a new
protocol file and some reader changes. It was built and tested on Windows only. The CI workflow targets Ubuntu and hasn't run yet.

## License

Code: MIT. The dataset has its own CC0 license and isn't included here.
