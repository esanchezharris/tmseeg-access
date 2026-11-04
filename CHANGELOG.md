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
- MATLAB export to `.mat` and EEGLAB `.set`, with round-trip tests.
- HTML report and CSVs built from saved results.
- Tutorial notebook, API reference, example queries, and privacy and MATLAB guides.
- GitHub Actions workflow for the synthetic tests.
- `scripts/rebuild_evidence.py`, which regenerates every saved result and generated doc.

### Known gaps

- MATLAB and EEGLAB opening of exports is untested: no MATLAB was available.
- The CI workflow has not run on GitHub. Its steps were run in a clean clone on Windows.
- Stimulation dose can't be joined, because the release doesn't include it per subject.
- Signal checks cover 10 subjects, chosen to include known problems.
