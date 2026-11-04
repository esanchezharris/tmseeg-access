# Notes: assumptions and evidence

Every assumption made about ds008037, and how it was checked. Numbers come from the file named
beside them. The plain-English neuroscience section is added at Checkpoint 3.

## Dataset

- **ds008037 v1.0.1** on OpenNeuro, CC0: "The neural dynamics of working memory and transcranial
  magnetic stimulation". Biabani, Rogasch and colleagues, Monash University.
- Preprint: <https://doi.org/10.64898/2026.07.12.738085>. Called "the preprint" below.
- Scale: see `results/dataset_facts.json` (123 subjects, 717 recordings, 479 TMS runs).
- `participants.tsv` holds age, sex, education, smoking status and cap size.

## What a TMS pulse looks like here

A pulse is a row in `*_task-tmseeg_acq-<site>_events.tsv` with `is_tms_pulse == 1`. The `value`
column holds the site name (for example `Parietal`). The site is the BIDS `acq` entity. There is no
pulse channel or EMG in the release, so markers are the only record of when a pulse happened.

**How this was checked** (`scripts/pulse_identification.py`, `results/pulse_identification.json`,
sub-001, all 4 sites):

1. `onset` equals `(EEGLAB latency - 1) / sampling rate`, with a maximum difference of about 6e-14 s.
   Compared with `latency / rate` it differs by 1 ms.
2. So `onset` is 0-based seconds, while the `sample` column is EEGLAB's 1-based latency. Using
   `sample` directly would shift every epoch by 1 ms. The package uses `onset` only.
3. The signal changes at fixed offsets from the markers, and does not when the same analysis is run
   on markers moved 1 s later (the placebo). Roughness here is the median absolute second difference.

| Site | At the markers | Peak vs baseline | Placebo |
|---|---|---|---|
| control | smoother at -1 to +5 ms | lowest 0.29× | no departures |
| parietal | smoother at -1 to +5 ms | lowest 0.27× | no departures |
| premotor | rougher at -3 to +11 ms | peak 6.3× | no departures |
| prefrontal | rougher at -10 to +22 ms | peak 396.8× | no departures |

Control and parietal match the preprint's stated interpolation window of -1 to 5 ms exactly.

## Findings so far

These are observations. Causes are unknown unless stated.

- **Frontal sites keep a large pulse-locked disturbance** in sub-001, despite the preprint's artifact
  step. It starts 10 ms before the prefrontal markers, so a baseline ending at the pulse would be
  contaminated. The quickstart baseline ends at -10 ms for this reason. This is one subject so far:
  Checkpoint 3 surveys more.
- **Marker pairs under 1 ms apart:** 243,139 gaps, and none exactly zero
  (`results/pulse_identification.json`). An equality test would find nothing, so duplicates are
  detected with a window. At the shared 1 kHz rate these pairs are indistinguishable from one pulse.
- **240 markers in 19 runs**, not 120 (`results/dataset_facts.json`). sub-136 parietal is exactly
  doubled (`results/quickstart.json`).
- **sub-071 prefrontal has 240,923 markers**, and sub-134 parietal has 401.
- **Spacing:** the preprint says 4 to 6 s. Of all gaps, 56,959 are 2.5 to 3.6 s and 13 are 4 to 6 s.
- **Channels:** 392 TMS sidecars declare 63 channels and 87 declare 62. `channels.tsv` agrees with
  the sidecar in every run. Header comparison needs the `.set` files, so it comes at Checkpoint 3.
- **Missing runs:** 479 of 492 expected TMS runs exist. `tmseeg_runs_missing_by_subject` lists the
  gaps.
- **Stimulation dose is not published per subject.** The preprint says 94 subjects received 100% and
  29 received 120% RMTadj. No JSON sidecar contains an intensity field, and `participants.tsv` has no
  dose column. `Dataset.metadata()` therefore cannot join stimulation intensity.
- **`*_nibs` files are absent.** Sidecars refer to them and `.bidsignore` lists them, but the release
  has none. `event_id` was meant to link to them.
- **`DatasetType` says `raw`**, while the preprint says partially preprocessed: downsampled from
  10 kHz to 1 kHz, with the artifact window interpolated.

## Assumptions

| # | Assumption | Basis | Status |
|---|---|---|---|
| A1 | `onset` is the true marker time | Matches `.set` latency | Checked on sub-001 |
| A2 | Markers align with pulses | Placebo-controlled signal check | Checked on sub-001 |
| A3 | Markers under 2 ms apart are one pulse | No gaps between 1 and 2 ms; only 1 from 2 to 10 ms | Assumption: the analyst must opt in to `keep_first` |
| A4 | Gaps of 10 ms to 2.5 s are not duplicates | 519 gaps with no explanation yet | Open: not treated as duplicates, reviewed at Checkpoint 3 |
| A5 | The `control` run is shoulder stimulation | `datacite.yml` and the preprint | It is a sensory control, not a sham coil |
| A6 | "Expected 120 pulses" | Preprint, and 411 of 479 runs | Used as the protocol value |
| A7 | Behaviour summaries are plain column statistics | See `behavior.py` | Convenience only, not validated scores |

## Data handling

- Data lives at `TMSEEG_DATA_ROOT`, outside this repo. On the build machine that is
  `E:\tms-eeg-data\ds008037`.
- The Windows health status of that drive is "Warning" and the cause was not investigated, so every
  file is verified against the release hash. After a second pass, 6,683 text files and 8 signal files
  passed (`results/verify_metadata.json`, `results/verify_signal_sub-001.json`).
- The drive is exFAT with a large cluster size, so the 410 MB of files take about 1.7 GB on disk.
