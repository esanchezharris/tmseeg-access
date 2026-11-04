"""Build and run docs/tutorial.ipynb. Saved outputs are real results from ds008037."""

from __future__ import annotations

from pathlib import Path

import nbformat
from nbclient import NotebookClient
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook

OUTPUT = Path(__file__).resolve().parents[1] / "docs" / "tutorial.ipynb"


def md(text: str):
    return new_markdown_cell(text.strip())


def code(text: str):
    return new_code_cell(text.strip())


CELLS = [
    md("""
# From "I have this dataset" to clean epochs around TMS pulses

This walks through finding a usable recording in ds008037, checking it, and cutting epochs around
its TMS pulses. It uses public, de-identified data.

**You will need** `TMSEEG_DATA_ROOT` set, and these already run:

```
tmseeg-access download --tier metadata
tmseeg-access download --tier signal --subjects sub-001 --tasks tmseeg
tmseeg-access catalog
tmseeg-access check
```

"Clean" here means the markers are trustworthy and known problems are avoided. These epochs have
not been through a full TMS-EEG cleaning pipeline, so they are a starting point for analysis.
"""),
    md("## 1. Open the dataset\n\nOpening it reads no signal."),
    code("""
import json

import matplotlib.pyplot as plt
import numpy as np

from tmseeg_access.catalog import default_path, query
from tmseeg_access.dataset import Dataset, DuplicatePulseError

ds = Dataset()
catalog = default_path(ds.root)
print(ds)
ds.recordings("sub-001")
"""),
    md("""
## 2. Find runs worth using

The catalog answers this with SQL. Here we look for parietal runs with 120 pulses and no
error-level issue, and join in participant fields.
"""),
    code("""
query(catalog, '''
    WITH problem_runs AS (
        SELECT DISTINCT recording_id FROM issues
        WHERE severity = 'error' AND recording_id IS NOT NULL
    )
    SELECT r.subject, p.age, p.sex, r.pulse_count, r.channels_sidecar, r.has_signal
    FROM recordings r
    JOIN participants p USING (subject)
    LEFT JOIN problem_runs x USING (recording_id)
    WHERE r.acquisition = 'parietal' AND r.pulse_count = 120 AND x.recording_id IS NULL
    ORDER BY r.has_signal DESC, r.subject
    LIMIT 5
''')
"""),
    md("## 3. Check what the quality rules say about this subject"),
    code("""
query(catalog, '''
    SELECT rule, severity, recording_id, "where", observed
    FROM issues WHERE subject = 'sub-001' ORDER BY severity, recording_id
''')
"""),
    md("""
sub-001's parietal run has no issues. Its prefrontal run does, which we come back to in step 6.

## 4. Look at the pulses

`pulses()` shows the markers as published, with their spacing. `is_duplicate` flags suspected
duplicates but removes nothing. Times come from `onset`, because the `sample` column is 1-based.
"""),
    code("""
pulses = ds.pulses("sub-001", "parietal")
print(len(pulses), "pulses,", int(pulses["is_duplicate"].sum()), "suspected duplicates")
pulses[["onset", "sample", "onset_sample", "gap_from_previous_s", "is_duplicate"]].head()
"""),
    md("""
## 5. Cut the epochs

`baseline` is off unless you ask for it, and we end it 10 ms before the pulse. Most recordings
carry a flat `TRIGGER` channel typed as EEG, so we exclude it by name. sub-001 does not have one,
so here that does nothing, but it makes this code safe for other subjects.

The choices made are stored with the epochs.
"""),
    code("""
epochs = ds.epochs_around_pulses(
    "sub-001", "parietal",
    tmin=-0.1, tmax=0.5,
    baseline=(-0.1, -0.01),
    exclude_channels=("TRIGGER",),
)
print(epochs)
print(json.dumps(json.loads(epochs.info["description"]), indent=2))
epochs.metadata.head(3)
"""),
    md("""
## 6. See why checking the run matters

Global field power (the spread across channels at each moment) summarises the response in one
line. Both runs below are from the same person and were processed the same way, but the prefrontal
run still contains the TMS artifact. Note how far apart the two scales are.
"""),
    code("""
def field_power(site):
    epochs = ds.epochs_around_pulses(
        "sub-001", site, tmin=-0.05, tmax=0.1, baseline=(-0.05, -0.01),
        exclude_channels=("TRIGGER",),
    )
    average = epochs.average()
    return average.times * 1000, average.data.std(axis=0) * 1e6

figure, axes = plt.subplots(1, 2, figsize=(9, 3), facecolor="#fcfcfb")
for axis, site in zip(axes, ["parietal", "prefrontal"]):
    times, power = field_power(site)
    print(f"{site}: field power peaks at {power.max():.1f} uV")
    axis.plot(times, power, color="#2a78d6", linewidth=1.6)
    axis.axvspan(-1, 5, color="#eeede9", linewidth=0)
    axis.set_title(f"sub-001 {site}", loc="left", fontsize=11)
    axis.set_xlabel("Time from pulse (ms)")
    axis.set_ylabel("Global field power (uV)")
    axis.set_facecolor("#fcfcfb")
    axis.spines[["top", "right"]].set_visible(False)
figure.tight_layout()
"""),
    md("""
The grey band is the -1 to 5 ms window the preprint says was interpolated. Compare the two y-axes:
the prefrontal run peaks far higher, and stays high until about 10 ms after the pulse, which the
parietal run does not.

The check in step 3 reported a much bigger number for this run, because it measures deviation on
each channel. Field power only counts differences between channels, so anything every channel shares
drops out. A large gap between the two means most of the artifact is common to all channels. That
would fit an artifact in the shared reference electrode, though this tutorial doesn't prove that.
Average referencing would remove the shared part, and leave what you see here.

## 7. When a run has doubled markers

Some runs have pulse markers recorded twice. Epoching refuses them by default, and explains why.
"""),
    code("""
try:
    ds.epochs_around_pulses("sub-136", "parietal")
except DuplicatePulseError as error:
    print(error)
"""),
    md("""
If you have reviewed the run and accept treating each pair as one pulse, say so. The choice is
recorded. If you need sub-136, first run:

```
tmseeg-access download --tier signal --subjects sub-136 --tasks tmseeg
```
"""),
    code("""
doubled = ds.epochs_around_pulses(
    "sub-136", "control", on_duplicate="keep_first", exclude_channels=("TRIGGER",),
)
record = json.loads(doubled.info["description"])
{key: record[key] for key in ["markers_in_events_tsv", "duplicates_removed", "channels_excluded"]}
"""),
    md("## 8. Hand the epochs to MATLAB\n\n`docs/matlab.md` shows how to open these files."),
    code("""
import tempfile
from pathlib import Path

from tmseeg_access.matlab import export_epochs_mat, read_epochs_mat

folder = Path(tempfile.mkdtemp())
path = export_epochs_mat(epochs, folder / "sub-001_parietal_epochs.mat")
back = read_epochs_mat(path)
print(back["data_uv"].shape, back["provenance"]["source"])
np.abs(back["data_uv"] - epochs.get_data() * 1e6).max()
"""),
]


def main() -> None:
    notebook = new_notebook(
        cells=CELLS,
        metadata={
            "kernelspec": {"name": "python3", "display_name": "Python 3", "language": "python"}
        },
    )
    NotebookClient(notebook, timeout=300, kernel_name="python3").execute()
    nbformat.write(notebook, OUTPUT)
    print(f"Wrote {OUTPUT}")


if __name__ == "__main__":
    main()
