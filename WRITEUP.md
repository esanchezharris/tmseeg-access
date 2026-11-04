# TMS-EEG data access toolkit: writeup

**What it does.** `tmseeg-access` is a tested Python package for a public TMS-EEG dataset (OpenNeuro
ds008037: 123 subjects, 479 TMS runs). Analysts get a simple API down to epochs around each pulse, a
DuckDB catalog of every recording and 301,143 pulse markers, quality checks with a clear record for each
issue, a de-identification step, MATLAB and EEGLAB export, and an HTML report.

**Design choices.**
- **Report, never repair.** Checks record what was seen, where, the rule and a suggested action. Doubled
  markers stop epoching until the analyst opts in, and that choice is saved with the epochs.
- **Metadata everywhere, signal where needed.** The catalog covers all subjects from text and headers.
  The 40 signal files here are 3.85 GB of 107.81 GB of signal, and a check that couldn't run counts as
  coverage, not a pass.
- **Keep sources apart.** Sidecar and header values stay in separate columns, and signal measures in their
  own file, because comparing them is the point. Published and observed protocol values are separate too.
- **Verify, don't assume.** Downloads are checked against release hashes, and one script rebuilds the
  evidence. Numbers in the docs trace to saved files. [AUDIT.md](AUDIT.md) records the review passes
  and what they changed.

**What the checks found.** There are 301 issues from 22 rules. The headlines:
- 243,139 of 301,143 markers are suspected duplicates, under 2 ms after the previous one. 240,801 are in
  one run, which also has about 20 s of frozen signal. The other 57 affected runs hold 2,338.
- Markers are 3.023 s apart at the median. The preprint says 4 to 6 s, and at most 15 of 57,525 gaps fit,
  however duplicates are handled.
- Sidecars state an FCz reference and the preprint states FPz. FPz is absent from 475 of 479 channel
  tables, and FCz carries signal in all 40 signal-checked runs, so the data as stored isn't in the FCz
  reference the sidecars state.
- 49 runs have pulse markers with more than one trigger code. In sub-134 parietal, 278 of the 398 markers
  left after duplicates aren't code 128, and averaging them in shrank a 2,697.8 uV peak to 814.3 uV.
- 20 of 40 signal-checked runs show a pulse artifact or a very large channel, and 13 reach 1,000 uV. All
  13 record interpolation in their headers, so the header can't tell you which runs are clean.
- `TRIGGER`, usually a flat channel, is typed as EEG in 392 runs, which explains the 62 versus 63 split.
- 47 runs share a header pattern that suggests separate processing.
- Per-subject stimulation dose isn't published, so it can't be joined.
- Also useful: all 432 available site codes match their labels, and sidecars agree with headers on all
  479 runs for rate, channel count, duration, channel names and event count.

These are observations. I don't know their causes, and the authors may have simple explanations. Checking
changed my own conclusions: the artifact isn't only frontal, smoothing at markers shows they match what
the authors processed but not that a pulse happened, and a median across channels missed artifacts.

**Limits.**
- Signal checks cover 10 subjects, chosen by hand mostly for known problems, so rates don't generalise.
- The placebo timing test covers sub-001 only. Time base checks cover all 479 runs.
- Sizes are in the data as stored, whose reference isn't confirmed. Some large values may be bad
  electrodes, not pulse artifact.
- It targets one dataset, and another would need a new protocol file and reader changes.
- Exports were opened in GNU Octave and EEGLAB, not in MATLAB itself.
- CI hasn't run on GitHub, only in a clean clone on Windows. It wasn't tested on Linux or a Mac.
- It's not Keller lab data, and it contains no iTBS. De-identification isn't a HIPAA certification.

**Next steps.**
1. Ask the authors about spacing, dose, the true reference, `*_nibs` files and trigger codes.
2. Run signal checks on all subjects.
3. Separate bad electrodes from pulse artifact.
4. Test the exports in MATLAB.
5. Add a BrainVision reader, the format in the lab's `Analysis-Physiology` pipeline.

## To say out loud

"I built a Python package that gives analysts clean access to a public TMS-EEG dataset, from a simple API
down to epochs around each pulse, with a SQL catalog of every recording. It treats data quality as a
first-class output: every issue records what was observed, where, the rule and a suggested action, and it
never silently fixes anything. Those checks found things you can't see in the file names, such as pulse
spacing that disagrees with the published protocol, a sidecar reference that disagrees with the preprint,
and runs with large deviations at the pulse even though their headers record interpolation. Review mattered
too: opening the exports in EEGLAB exposed false events my Python test had missed, and a separate AI review
agent recomputed the findings from the raw files, which changed three claims. It's the kind of work that
replaces a hand-kept list of bad recordings with something repeatable."
