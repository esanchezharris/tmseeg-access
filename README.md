# tmseeg-access

Clean, fast access to a public TMS-EEG dataset and its metadata, with data quality checks.

Built around [OpenNeuro ds008037](https://openneuro.org/datasets/ds008037) (v1.0.1, CC0). It uses
public, de-identified data only.

> Work in progress. The data API and metadata catalog are working. Quality checks, de-identification,
> MATLAB export and reporting are next.

## Install

Needs [uv](https://docs.astral.sh/uv/).

```bash
uv sync
```

## Quickstart

Tell the package where the data should live. This folder can be anywhere, and it needs about 0.5 GB
for this quickstart.

```bash
export TMSEEG_DATA_ROOT=/path/to/ds008037
```

On Windows PowerShell, use `$env:TMSEEG_DATA_ROOT = "E:\tms-eeg-data\ds008037"`.

Download the text metadata for every subject, plus one subject's TMS signal. Every file is checked
against the release's own hashes.

```bash
uv run tmseeg-access download --tier metadata
```

```bash
uv run tmseeg-access download --tier signal --subjects sub-001 --tasks tmseeg
```

Build the catalog, then try it:

```bash
uv run tmseeg-access catalog
```

```bash
uv run tmseeg-access query "SELECT acquisition, count(*) AS runs FROM recordings WHERE task = 'tmseeg' GROUP BY 1"
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
    "sub-001", "parietal", tmin=-0.1, tmax=0.5, baseline=(-0.1, -0.01)
)
```

`examples/quickstart.py` runs all of this end to end.

### Ambiguous pulses stop the analysis

Some runs have doubled pulse markers. `epochs_around_pulses` refuses them by default and says why.
To continue, make the choice explicit. It is recorded in `epochs.info["description"]`:

```python
ds.epochs_around_pulses("sub-136", "parietal", on_duplicate="keep_first")
```

## Tests

```bash
uv run pytest
```

Tests use small synthetic fixtures. Tests on the real data skip unless `TMSEEG_DATA_ROOT` is set.

See `NOTES.md` for what a pulse looks like in this dataset and how that was verified.
