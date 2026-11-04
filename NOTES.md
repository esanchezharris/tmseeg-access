# Notes: the science, the assumptions and the evidence

Written for a software engineer. The first half explains the science well enough to discuss it in an
interview. The second half records every assumption made about ds008037 and how it was checked.
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
often said to raise excitability, and Solomon et al. tested that. ds008037 doesn't contain iTBS. It uses
single pulses to probe the brain, not to change it.

**BIDS (Brain Imaging Data Structure)** is a standard for organising neuroscience data: fixed folder and
file names such as `sub-001_task-tmseeg_acq-parietal_eeg.set`, with sidecar JSON and TSV files beside
each recording. Software can then find data and its metadata without custom parsing. For an engineer,
it's a schema expressed as a file system, which is what makes this package possible.

## How the lab work relates to this project

- No Keller or Solomon data is public yet, so this project uses a comparable public dataset.
- **Solomon et al. (the iTBS paper) is not scalp TMS-EEG.** It's mainly intracranial: 20 neurosurgical
  patients with electrical iTBS and depth electrodes, plus 3 patients with iTBS delivered by TMS.
- The lab's scalp TMS-EEG code is `Analysis-Physiology`. It's MATLAB, reads BrainVision files, and keeps
  a hand-written skip list of blocks with missing pulse events. This package's checks automate that
  kind of list, and the MATLAB export exists because that's what the lab's pipeline uses.

## What a TMS pulse looks like here

A pulse is a row in `*_task-tmseeg_acq-<site>_events.tsv` with `is_tms_pulse == 1`. The `value` column
holds the site name. There's no pulse channel or EMG in the release, so markers are the only record.

Checked on sub-001, all 4 sites (`results/pulse_identification.json`):

1. `onset` equals `(EEGLAB latency - 1) / sampling rate`, to within about 6e-14 s.
2. So `onset` is 0-based seconds, and the `sample` column is EEGLAB's 1-based latency. Using `sample`
   directly would shift every epoch by 1 ms. The package uses `onset` only.
3. The signal changes at fixed offsets from the markers, and doesn't when the same analysis is run on
   markers moved 1 s later (a placebo). So the time base is right.

**What that does and doesn't prove.** Interpolation was applied at the markers, so smoothing there shows
my timing matches the markers the authors processed. It doesn't show a pulse physically happened at
each one. In sub-057 parietal, both markers of every 0.100 s pair are interpolated, so the signal can't
say which, if either, is the real pulse. Only runs with an intact artifact show a pulse directly.

## What the checks found

Scope: event checks and header checks ran on all 479 TMS runs. Signal checks ran on 40 runs from 10
subjects, **chosen to include known problems, so they aren't a random sample**. There are 208 issues in
`results/issues.csv`. The report is `results/report/report.html`.

**Pulse markers**
- 243,139 markers sit under 2 ms from the previous one, and none are exactly equal. Equality checks
  would find nothing, so duplicates are found with a window. The largest gap among the 58 affected runs
  is 0.2 ms.
- 19 runs have 240 markers, and 411 of 479 have the planned 120.
- sub-071 prefrontal has 240,923 markers: 11 bursts of ticks lasting up to 4.94 s, which could hide real
  pulses (`pulse.marker_burst`).
- sub-047 prefrontal and sub-057 parietal have 120 marker pairs exactly 0.100 s apart. Unexplained.
- sub-134 parietal has 401 markers in a repeating pattern, and a TRIGGER channel that isn't flat.
- All 520 gaps between 2 ms and 2.5 s come from 5 runs (`pulse.gap_short`).

**Spacing.** The preprint gives 4 to 6 s. The median gap between distinct pulses is 3.023 s, and 13 of
57,525 gaps fall in the published range. One of the two is wrong, or they describe different things. I
can't tell which, and it needs the authors.

**The pulse artifact is often still in the signal.** 18 of 40 signal-checked runs keep one, and 8 peak at
1,000 uV or more, up to 15,983.5 uV against about 10 uV in clean runs. By site, 9 of 10 prefrontal runs
are flagged, 4 premotor, 4 parietal and 1 control. My first impression that this was a frontal problem
was too simple: sub-019 and sub-147 have huge artifacts at parietal, while sub-019 prefrontal is mild.

Two things to be careful about with that number:
- It's deviation per channel, in the recorded reference (FCz). Field power, which counts only differences
  between channels, is often far smaller: sub-001 prefrontal is 9,800.6 uV deviation but 300.3 uV field
  power. So much of the artifact is shared across channels, which would fit an artifact in the reference
  electrode. That's a hypothesis, not a finding, and sub-019 parietal goes the other way.
- Average referencing would remove the shared part, so analysts won't see the full figure after it.

**Headers don't predict the signal.** All 8 runs over 1,000 uV record interpolation in their header. In
the other direction, sub-125 has no artifact record, yet all four of its runs look interpolated and peak
under 10 uV. Only the signal tells you.

**A second processing batch.** 47 runs in 12 subjects share a pattern: no artifact record, mixed-case
channel names, no TRIGGER channel and no site code (`results/header_provenance.json`). They're every
mixed-case run in the dataset. One subject sampled from it (sub-125) looked clean. sub-136 isn't in it,
so that doesn't explain sub-136.

**Channels.** The 62 versus 63 split is a flat channel called `TRIGGER`, which `channels.tsv` types as EEG
in 392 runs. MNE loads it as EEG, so it would distort an average reference. Use
`exclude_channels=("TRIGGER",)`. sub-023 has `FPZ` where other subjects have `FCZ`.

**Metadata**
- No per-subject stimulation dose is published. The preprint reports 94 subjects at 100% and 29 at 120%
  RMTadj, so `Dataset.metadata()` can't join intensity. This is the biggest gap against the brief.
- Sidecars point to `*_nibs` files, and `.bidsignore` lists them, but the release has none.
- `DatasetType` says `raw`. The preprint says partly preprocessed.
- 13 of 492 expected TMS runs are absent, across 6 subjects.

**What came back clean.** Site labels agree with original filenames in all 432 runs that have a code, so
mislabelling is ruled out. Control runs are coded `SHAM` in those filenames. Sampling rates are uniform,
and sidecars, `channels.tsv`, events and headers agree on all 479 runs. No flat or clipped EEG channels
turned up in the 40 signal-checked runs. No two recordings are identical files.

## Assumptions

| # | Assumption | Basis | Status |
|---|---|---|---|
| A1 | `onset` is the marker's true time | Matches `.set` latency | Checked on sub-001 |
| A2 | The time base aligns markers to signal | Placebo-controlled check | Checked on sub-001, 4 sites |
| A3 | Markers under 2 ms apart are one pulse | Gaps stop at 0.2 ms, then nothing until over 2 ms | Assumption: the analyst must opt in to `keep_first` |
| A4 | Gaps of 2 ms to 2.5 s are not duplicates | From 5 runs, with patterns I can't explain | Flagged, not resolved |
| A5 | The `control` run is shoulder stimulation | `datacite.yml`, preprint | A sensory control, though filenames say SHAM |
| A6 | Each run should have 120 pulses | Preprint, and 411 of 479 runs | Used as the protocol value |
| A7 | Behaviour summaries are plain column statistics | `behavior.py` | Convenience only, not validated scores |
| A8 | The observed 2.5 to 3.6 s band is normal here | 56,959 gaps | A description of this release, not the protocol |

## Data handling

- Data lives at `TMSEEG_DATA_ROOT`, outside this repo. On the build machine that's
  `E:\tms-eeg-data\ds008037`.
- That drive's Windows health status is "Warning", and the cause wasn't investigated, so every file is
  verified against the release hash. Reruns re-verify: see `results/verify_*.json`.
- Downloaded: text metadata for all subjects, `.set` headers for all 479 TMS runs, and TMS signal for 10
  subjects (`results/dataset_facts.json`).
