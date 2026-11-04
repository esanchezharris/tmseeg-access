# Notes: the science, the assumptions and the evidence

The first half explains the science for a software engineer. The second half records every assumption
made about ds008037 and how it was checked.
Measured numbers come from the file named beside them, and quoted ones from
`results/published_values.json`.

## The science in plain English

**EEG (electroencephalography)** records the brain's electrical activity through electrodes on the
scalp. The signal is tiny, measured in microvolts (uV), and it has excellent timing: you can see
changes millisecond by millisecond. It's a time series with many channels, one per electrode.

**TMS (transcranial magnetic stimulation)** is a coil held against the head that sends a brief, strong
magnetic pulse through the skull. That pulse induces a small current in the brain underneath and makes
those neurons fire. It's non-invasive, and it's a treatment for depression as well as a research tool.
If a TMS pulse is like knocking on something to hear how it rings, EEG is the microphone.

**TMS-EEG** combines the two: stimulate one spot, and record how the whole brain responds. Ordinary
imaging shows which areas tend to be active together. TMS-EEG goes further, because you caused the
activity, so you can measure how excitable an area is and how signals travel from it.

**The TMS-evoked potential (TEP)** is the response itself. A single response is buried in noise, so you
repeat the pulse many times, line up the recording around each pulse (each slice is an **epoch**), and
average. Random noise cancels out, and what's time-locked to the pulse remains. That's why timing is
everything: averaging only works if you know exactly when each pulse happened.

**Why artifacts matter.** The pulse is enormous compared with brain signals, and the amplifier sees it.
That produces a huge spike, followed by decay and muscle twitches from the scalp, in exactly the early
window where you most want to read the brain's response. A common fix is to cut out a few milliseconds
around each pulse and interpolate across the gap. If that fails, what looks like brain response can
really be artifact. Sites near scalp muscles are often harder.

**Sham and control conditions.** A TMS pulse also makes a loud click and a tap on the scalp, which evoke
brain responses of their own. A sham or control run tries to reproduce those sensations without
stimulating the same brain area. In ds008037 the control run stimulates the shoulder.

**iTBS (intermittent theta burst stimulation)** is a treatment-style protocol: rapid bursts of pulses
rather than single pulses, described by Solomon et al. as 50 Hz triplets delivered in 5 Hz bursts. It's
often said to raise excitability. ds008037 doesn't contain iTBS. It uses
single pulses to probe the brain, not to change it.

**BIDS (Brain Imaging Data Structure)** is a standard for organising neuroscience data: fixed folder and
file names such as `sub-001_task-tmseeg_acq-parietal_eeg.set`, with sidecar JSON and TSV files beside
each recording. Software can then find data and its metadata without custom parsing. For an engineer,
it's a schema expressed as a file system, which is what makes this package possible.

## How the lab work relates to this project

- I found no public Keller or Solomon dataset. Solomon et al. says data will be released on publication,
  so this project uses a comparable public dataset.
- **Solomon et al. (the iTBS paper) is not scalp TMS-EEG.** It's mainly intracranial: 20 neurosurgical
  patients with electrical iTBS recorded by stereo-EEG, plus 3 patients with iTBS delivered by TMS.
- The lab's scalp TMS-EEG code is `Analysis-Physiology`, in MATLAB and notebooks. It reads BrainVision
  files and keeps a hand-written skip list of blocks with missing pulse events. This package's checks
  automate that kind of list, and the MATLAB export exists because the pipeline is in MATLAB. Details,
  with the commit, are in `results/published_values.json`.

## What a TMS pulse looks like here

A pulse is a row in `*_task-tmseeg_acq-<site>_events.tsv` with `is_tms_pulse == 1`. The `value` column
holds the site name. There's no EMG, and `TRIGGER` was flat in 31 of the 32 signal-checked runs that have it, so markers are
the main record.

Three things were checked:

1. **Time base, all 479 runs** (`results/hand_checks.json`). Every `onset` equals
   `(EEGLAB latency - 1) / sampling rate`, to within about 1e-13 s. So `onset` is 0-based seconds, and the
   `sample` column is EEGLAB's 1-based latency. Using `sample` directly would shift every epoch by 1 ms.
   The package uses `onset` only.
2. **Alignment with the signal, sub-001, 4 runs** (`results/pulse_identification.json`). The signal
   changes at fixed offsets from the markers, and doesn't when the same analysis is run on markers moved
   1 s later (a placebo).
3. **A change around the markers in all 40 signal-checked runs**: the 20 unflagged runs have smoothed
   offsets, and the 20 flagged runs have roughness or smoothing. The placebo was only run on sub-001.

**What that does and doesn't prove.** Interpolation was applied at the markers, so smoothing there shows
my timing matches the markers the authors processed. It doesn't show a pulse physically happened at
each one. In sub-057 parietal, the median signal across the 120 pairs about 0.1 s apart is smoothed at both
markers, so smoothing can't say which, if either, is the real pulse. Only runs with an intact artifact
show a pulse directly.

Smoothing can also appear with no pulse at all. In sub-134 parietal the markers with other trigger codes
show no artifact, yet all 7 offsets in the window are smooth.

## What the checks found

Scope: event and header checks ran on all 479 TMS runs. Signal checks ran on 40 runs from 10 subjects,
**chosen by hand, mostly for known problems, so their rates don't apply to the whole dataset**. There are
301 issues in `results/issues.csv`, from 22 rules. The report is `results/report/report.html`.

**Pulse markers**
- 243,139 markers sit under 2 ms from the previous one, and none are exactly equal, so suspected
  duplicates are found with a window. 240,801 of them are in one run, sub-071 prefrontal. The other 57
  affected runs hold 2,338. The largest gap flagged in those runs is 0.2 ms. Removing them leaves 58,004
  markers, which isn't a pulse count, because some carry codes that don't look like pulses.
- sub-071 prefrontal has 240,923 markers: 11 bursts lasting up to 4.94 s, which could hide real pulses.
  It also has 20,181 samples, about 20 s, where most channels stop changing (`signal.frozen_signal`).
- 49 runs carry more than one original trigger code (`pulse.mixed_marker_codes`). 25 runs have codes 128
  and 191, which is a likely reason for many doubled markers: 15 of them have 120 of each. It's not proven,
  and I can't tell why a pulse would get two codes.
- 19 runs have 240 markers, and 411 of 479 have the planned 120.
- sub-047 prefrontal and sub-057 parietal have 120 marker pairs 0.0999 s apart. Unexplained.
- sub-134 parietal has 401 markers. Only 120 are code 128, the usual pulse code, and it has a TRIGGER
  channel that isn't flat. Measured on all markers its peak is 814.3 uV, and on code 128 alone it's
  2,697.8 uV (`sub_134_parietal_by_trigger_code` in `results/hand_checks.json`).
- All 520 gaps between 2 ms and 2.5 s come from 5 runs (`pulse.gap_short`).

**Spacing.** The preprint gives 4 to 6 s, jittered. Counting every gap of 2 ms or more, the median gap
between markers is 3.023 s, and 13 of 57,525 gaps fall in the published range. That count depends on the
rule: 15 between markers kept by `keep_first`, and 1 in runs with no suspected duplicates
(`spacing_variants` in `results/hand_checks.json`). The conclusion holds either way. One of the two is
wrong, or they describe different things. I can't tell which, and it needs the authors.

**A pulse artifact or a very large channel remains in half the signal-checked sample.** 20 of 40 runs are
flagged, and 13 reach 1,000 uV or more on at least one measure, up to 94,308.1 uV. Those sizes are
averages across a run's pulses, so single pulses can be larger. sub-134 parietal would make 14, if measured
on code 128 alone. By site, 9 of 10 prefrontal runs are
flagged, then 5 premotor, 4 parietal and 2 control. It isn't only a frontal problem: sub-019 and sub-147
have large values at parietal.

Three measures are saved for each run in `results/pulse_artifact.csv`, because they disagree:

| Measure | What it sees | What it misses |
|---|---|---|
| Median deviation | Artifacts on most channels | An artifact on a few channels |
| Peak channel | The worst single averaged channel | A bad electrode looks like an artifact |
| Field power | Differences between channels | Anything all channels share |

My first version used only median deviation, and an audit found it missed runs: sub-147 control looks
clean on that measure (19.5 uV) while its F1 channel reaches 14,085.2 uV. A flat TRIGGER channel also
inflated field power, so it's now left out. Runs with no flag are not spotless: their peak channel has a
median of 45.0 uV and a maximum of 316.9 uV.

Some of this may be bad electrodes, not pulse artifact: PO4 is the worst channel in all four sub-019 runs,
three of them above 1,000 uV, and F1 in two sub-147 runs. Average referencing doesn't reliably help. It
ranges from making the worst channel 14.6 times smaller to about 1.07 times larger, which it did in 2 of
13 runs
(`average_reference_effect` in `results/hand_checks.json`).

**Headers don't predict the signal.** All 13 large runs record interpolation in their header, and 10 of
them have no sample in the window smoother than baseline. That doesn't show interpolation was skipped,
because a large interpolated curve still reads as rough. In the other direction, sub-125 has no artifact record, yet
all four runs look fully interpolated and none is flagged.

**The stated reference disagrees with the preprint.** Sidecars say FCz, and the preprint says recordings
were online-referenced to FPz and grounded to AFz. The sidecars' ground matches. FPz is absent from 475 of
479 channel tables, as a reference channel would be, and FCz carries signal in all 40 signal-checked runs,
so the data as stored can't be FCz-referenced (`sidecar.reference_differs_from_published`,
`signal.reference_channel_active`). The `reference` column in all 479 channel tables also says FCz,
repeating the sidecar. This suggests FPz is right, but the preprint doesn't say the shared
data stayed in that reference, so re-reference explicitly before analysis.

**A separate header pattern.** 47 runs in 12 subjects share a pattern that suggests separate processing:
no artifact record, mixed-case channel names, no TRIGGER channel and no site code
(`results/header_provenance.json`). No other run has mixed-case names. The one subject sampled from it,
sub-125, looked clean.

**Channels.** The 62 versus 63 split is a channel called `TRIGGER`, which `channels.tsv` types as EEG in
392 runs. MNE loads it as EEG. It was flat in 31 of the 32 signal-checked runs that have it, so it would
distort an average reference. Use `exclude_channels=("TRIGGER",)`. sub-023 has `FPZ` where other subjects
have `FCZ`, in its 4 TMS channel tables, the 4 that list FPz.

**Metadata**
- No per-subject stimulation dose is published. The preprint reports 94 subjects at 100% and 29 at 120%
  RMTadj, so `Dataset.metadata()` can't join intensity. This is the biggest gap for dose analysis.
- Sidecars point to `*_nibs` files, and `.bidsignore` lists them, but the release has none.
- `DatasetType` says `raw`. The preprint says partially pre-processed.
- 13 of 492 expected TMS runs are absent, across 6 subjects.

**What came back clean.**
- Site labels agree with original filenames in all 432 runs that have a code. The other 47 have no code,
  so they can't be checked this way. Control runs are coded `SHAM` in those filenames.
- Sampling rates are uniform.
- Sidecars, `channels.tsv` and headers agree on all 479 runs on sampling rate, channel count, duration,
  channel names and order, and event count. Event times match to about 1e-13 s.
- No flat channels turned up in the 40 signal-checked runs, apart from `TRIGGER`. No channel was clipped
  either, but that rule looks for 20 identical samples at a channel's extreme, which is a weak test on
  downsampled data. It missed the frozen signal in sub-071 prefrontal, which is why that has its own rule.
- No two recordings are identical files.

## Assumptions

| # | Assumption | Basis | Status |
|---|---|---|---|
| A1 | `onset` is the marker's true time | Matches `.set` latency | Checked on all 479 runs |
| A2 | The time base aligns markers to signal | Placebo-controlled check | Checked on sub-001, 4 sites |
| A3 | Markers under 2 ms apart are one pulse | Gaps stop at 0.2 ms, then nothing until over 2 ms | Assumption: the analyst must opt in to `keep_first` |
| A4 | Gaps of 2 ms to 2.5 s are not duplicates | From 5 runs, with patterns I can't explain | Flagged, not resolved |
| A9 | Deviations are measured in the data as stored | The sidecar reference disagrees with the preprint | Sizes depend on the true reference, which isn't confirmed |
| A5 | The `control` run is shoulder stimulation | `datacite.yml`, preprint | A sensory control, though filenames say SHAM |
| A6 | Each run should have 120 pulses | Preprint, and 411 of 479 runs | Used as the protocol value |
| A7 | Behaviour summaries are plain column statistics | `behavior.py` | Convenience only, not validated scores |
| A8 | The observed 2.5 to 3.6 s band is normal here | 56,959 gaps | A description of this release, not the protocol |

## Data handling

- Data lives at `TMSEEG_DATA_ROOT`, outside this repo. On the build machine that's
  `E:\tms-eeg-data\ds008037`.
- Windows reports that drive as "Warning" and "Full Repair Needed" (`results/drive_status.json`). The
  cause wasn't investigated, so every file is verified against the release hash. Reruns re-verify: see
  `results/verify_*.json`.
- Downloaded: text metadata for all subjects, `.set` headers for all 479 TMS runs, and TMS signal for 10
  subjects (`coverage` in `results/check_summary.json`).
- `scripts/rebuild_evidence.py` rebuilds the catalog, checks, report, evidence files and generated docs.
  Download logs, drive status, the CI simulation and hand-written quotes are recorded separately.
