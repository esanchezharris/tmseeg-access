# API reference

Generated from docstrings by `scripts/build_api_docs.py`.

The command line tool is `tmseeg-access`. Run `tmseeg-access --help` for its commands.

## `tmseeg_access.dataset`

The analyst-facing API: subjects, recordings, metadata, raw data and epochs around pulses.

Tables are read on first use and kept in memory. Signal is opened lazily through MNE, so listing
and filtering never touch the large binary files. Nothing here repairs or drops data without being
told to: ambiguous pulses raise an error that names the problem.

ds008037 has no BIDS sessions. Stimulation site is the ``acquisition`` entity (``parietal``,
``prefrontal``, ``premotor``, ``control``).

### `Dataset`

A local copy of a BIDS TMS-EEG dataset.

Parameters
----------
path
    Dataset root. Defaults to the ``TMSEEG_DATA_ROOT`` environment variable.
cache_size
    How many opened raw recordings to keep in memory.

#### `Dataset.__init__(self, path: "str | os.PathLike | None" = None, cache_size: "int" = 4) -> "None"`

Initialize self.  See help(type(self)) for accurate signature.

#### `Dataset.behavior(self, task: "str") -> "pd.DataFrame"`

Trial-level behavioural data for one task, across all subjects that have it.

#### `Dataset.behavior_summary(self) -> "pd.DataFrame"`

One row per subject. See ``tmseeg_access.behavior.SUMMARIES`` for the definitions.

#### `Dataset.epochs_around_pulses(self, subject: "str", acquisition: "str", tmin: "float" = -0.1, tmax: "float" = 0.5, baseline: "tuple[float | None, float | None] | None" = None, on_duplicate: "str" = "error", duplicate_gap_s: "float" = 0.002, exclude_channels: "Sequence[str]" = (), task: "str" = "tmseeg") -> "mne.Epochs"`

Cut epochs around each TMS pulse.

``on_duplicate="error"`` (the default) refuses to continue if any markers are closer than
``duplicate_gap_s``. ``"keep_first"`` keeps the first marker of each group.

Channels are only removed if named in ``exclude_channels``. Most TMS runs have a
``TRIGGER`` channel typed as EEG, usually flat, so pass ``exclude_channels=("TRIGGER",)`` before average
referencing. Names that a recording does not have are ignored.

These choices, and what they removed, are recorded in ``epochs.info["description"]`` as
JSON, and each epoch's source marker is in ``epochs.metadata``. No baseline is applied
unless asked.

#### `Dataset.events(self, subject: "str", task: "str" = "tmseeg", acquisition: "str | None" = None) -> "pd.DataFrame"`

The recording's ``events.tsv`` exactly as published.

#### `Dataset.load_raw(self, subject: "str", session: "str | None" = None, task: "str" = "tmseeg", acquisition: "str | None" = None, preload: "bool" = False) -> "mne.io.BaseRaw"`

Open one recording. Returns a copy, so editing it cannot affect the cache.

#### `Dataset.metadata(self, behavior: "bool" = True) -> "pd.DataFrame"`

Recordings joined to participant fields and, optionally, behavioural summaries.

ds008037 publishes no per-subject stimulation intensity, so none appears here. See
NOTES.md.

#### `Dataset.pulses(self, subject: "str", acquisition: "str", task: "str" = "tmseeg", duplicate_gap_s: "float" = 0.002) -> "pd.DataFrame"`

TMS pulse markers with their spacing, and suspected duplicates flagged, not removed.

``onset_sample`` is the 0-based sample for MNE, computed from ``onset``. The published
``sample`` column is EEGLAB's 1-based latency, so it is deliberately not used here.

#### `Dataset.recording_summary(self) -> "pd.DataFrame"`

One row per recording, built from text metadata only.

#### `Dataset.recordings(self, subject: "str | None" = None, task: "str | None" = None) -> "pd.DataFrame"`

List recordings, showing whether each one's signal is available locally.

#### `Dataset.sessions(self, subject: "str") -> "list[str]"`

BIDS sessions for a subject. Empty when the dataset has no session level.

#### `Dataset.subjects(self) -> "list[str]"`

Every subject in ``participants.tsv``, including any with no EEG files.

### `DataNotLocalError`

The recording exists in the dataset but its signal has not been downloaded.

### `DuplicatePulseError`

Pulse markers sit too close together to be separate pulses.

## `tmseeg_access.catalog`

A DuckDB catalog, so analysts can answer questions about the dataset with SQL.

Every recording is indexed from text metadata, whether or not its signal has been downloaded.
Header values appear only where the ``.set`` file is local, and stay NULL otherwise, so a query can
tell "not checked" from "fine". Values from different sources are kept in separate columns rather
than merged, because comparing them is the point.

### `build_catalog`

`build_catalog(ds: "Dataset", path: "Path | None" = None, tag: "str" = "1.0.1") -> "dict"`

Build the catalog from scratch. The new file replaces the old one only once complete.

### `query`

`query(path: "Path", sql: "str") -> "pd.DataFrame"`

Run read-only SQL against a catalog.

### `store_issues`

`store_issues(path: "Path", issues: "pd.DataFrame") -> "None"`

Save quality check results in the catalog, so they can be joined to recordings.

### `read_set_header`

`read_set_header(path: "Path") -> "dict[str, float]"`

Read channel count, length and rate from a ``.set`` file, without touching the signal.

## `tmseeg_access.checks.run`

Run every check that the local files allow, and say which ones could not run.

A check that cannot run is reported as coverage, not treated as a pass.

### `run_all`

`run_all(ds: "Dataset", protocol: "dict | None" = None) -> "tuple[pd.DataFrame, dict]"`

Run all checks. Returns the issues, and a summary of what each tier covered.

## `tmseeg_access.checks.issues`

The shared record every check produces, and the protocol values checks compare against.

### `Issue`

One finding: what was observed, where, under which rule, and what to do about it.

Checks only ever report. Fixing or excluding data is the analyst's decision.

#### `Issue.__init__(self, rule: "str", severity: "str", where: "str", observed: "str", expected: "str", suggested_action: "str", subject: "str | None" = None, recording_id: "str | None" = None) -> None`

Initialize self.  See help(type(self)) for accurate signature.

### `issues_frame`

`issues_frame(issues: "list[Issue]") -> "pd.DataFrame"`

Turn issues into a table with stable columns, even when there are none.

### `load_protocol`

`load_protocol(name: "str" = "ds008037") -> "dict"`

Load a protocol file shipped with the package.

## `tmseeg_access.deidentify`

Make a de-identified copy of a dataset. The source is never modified.

This removes specific identifying fields from headers and sidecars, and shifts dates. It does not
make a dataset anonymous, and it is not a certification of HIPAA compliance. See docs/privacy.md for
what it covers and what it leaves. The log records what changed, never the removed values.

### `deidentify`

`deidentify(source: "Path", output: "Path", subjects: "Sequence[str] | None" = None, key: "bytes | None" = None, drop_participant_columns: "Sequence[str]" = (), drop_head_geometry: "bool" = False, include_signal: "bool" = True) -> "dict"`

Write a de-identified copy of ``source`` to ``output`` and return what was done.

``key`` makes date shifts repeatable. Without one, a random key is used and discarded, so the
shifts cannot be reversed.

### `scan_set_header`

`scan_set_header(path: "Path") -> "list[str]"`

Return the names of top-level fields that still hold suspicious text.

## `tmseeg_access.matlab`

Export epochs and metadata so MATLAB users can work with the same data.

Two epoch formats. ``.mat`` is a plain structure, with signal in microvolts as trials x channels x
samples, for direct use in MATLAB. ``.set`` opens in EEGLAB. EEGLAB files cannot carry the per-epoch
table or provenance, so those are written beside the ``.set`` file.

### `export_epochs_mat`

`export_epochs_mat(epochs: "mne.Epochs", path: "Path") -> "Path"`

Write epochs, times, channel names, the per-epoch table and provenance to a ``.mat`` file.

### `read_epochs_mat`

`read_epochs_mat(path: "Path") -> "dict"`

Read a ``.mat`` export back into Python. Used to verify the round trip.

### `export_epochs_set`

`export_epochs_set(epochs: "mne.Epochs", path: "Path") -> "Path"`

Write an EEGLAB ``.set`` file, with its epoch table and provenance beside it.

### `export_metadata`

`export_metadata(table: "pd.DataFrame", path: "Path") -> "Path"`

Write a metadata table to a ``.mat`` structure with one field per column.

## `tmseeg_access.report`

Write an HTML report and CSVs from saved results. Reads the catalog and check outputs only.

The report never touches the signal or recomputes a check, so it can be rebuilt in seconds and every
figure in it can be traced to ``issues.csv``, ``pulse_artifact.csv`` or the catalog.

### `load_inputs`

`load_inputs(catalog: "Path", results: "Path") -> "Inputs"`

Read everything the report needs from saved files.

### `write_report`

`write_report(inputs: "Inputs", output: "Path") -> "Path"`

Write ``report.html``, chart images, CSVs and ``report_facts.json`` to ``output``.

## `tmseeg_access.download`

Fetch a pinned OpenNeuro snapshot, verifying every file against the release's own hashes.

Annexed files (the large binaries) carry a git-annex key holding their SHA-256. Other files are
identified by their git blob SHA-1. URLs are version-pinned, so a snapshot cannot change underneath
us. Files are written to ``<name>.part`` beside the target and renamed only after verification, so
a partial or corrupt file never appears under its real name.

### `fetch_manifest`

`fetch_manifest(dataset: "str", tag: "str", timeout: "int" = 280) -> "list[RemoteFile]"`

Ask OpenNeuro for every file in one snapshot.

### `select_files`

`select_files(files: "Iterable[RemoteFile]", tier: "str", subjects: "Sequence[str] | None" = None, tasks: "Sequence[str] | None" = None) -> "list[RemoteFile]"`

Pick files by tier: ``metadata`` (text), ``headers`` (.set), or ``signal`` (.set + .fdt).

### `download_files`

`download_files(files: "Sequence[RemoteFile]", root: "Path", workers: "int" = 8) -> "dict"`

Fetch many files concurrently. Any failure is reported, never hidden.
