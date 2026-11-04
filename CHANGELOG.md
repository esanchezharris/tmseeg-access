# Changelog

## 0.1.0 (unreleased)

First version, built around OpenNeuro ds008037 v1.0.1.

### Added

- `Dataset` API: subjects, sessions, recordings, joined metadata, behaviour, events, pulses, lazy raw
  loading with a cache, and epochs around pulses.
- Epoching refuses doubled pulse markers by default. `on_duplicate="keep_first"` opts in, and
  `exclude_channels` removes named channels. Both choices are recorded with the epochs.
- Checksummed downloader for a pinned OpenNeuro snapshot. Partial files never appear under their real
  name.
- DuckDB catalog of recordings, participants, behaviour, pulses, files and issues.
- Quality checks on pulse timing, channel and rate consistency, sidecars against headers, header
  provenance and the signal, reporting through one shared `Issue` record.
- `deidentify` step that works on a copy, with a post-run scan and a log of counts.
- MATLAB export to `.mat` and EEGLAB `.set`, with round-trip tests and a test in GNU Octave and EEGLAB.
- HTML report and CSVs built from saved results.
- Tutorial notebook, API reference, example queries, and privacy and MATLAB guides.
- GitHub Actions workflow for the synthetic tests.
- `scripts/rebuild_evidence.py`, which rebuilds the catalog, checks, report, evidence and generated docs.

### Fixed before release

- EEGLAB exports held false events, because raw-time annotations were read as epoch positions.
- Added rules for mixed trigger codes, frozen signal, and a sidecar reference that differs from the
  preprint. See [AUDIT.md](AUDIT.md).

### Known gaps

- Exports were tested in GNU Octave and EEGLAB, not in MATLAB itself. `struct2table` is unrun.
- The CI workflow has not run on GitHub. Its steps were run in a clean clone on Windows. Linux and Mac
  are untested.
- Stimulation dose can't be joined, because the release doesn't include it per subject.
- Signal checks cover 10 subjects, chosen by hand mostly for known problems.
