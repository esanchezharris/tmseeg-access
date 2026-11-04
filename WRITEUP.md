# TMS-EEG data access toolkit: writeup

**What it does.** `tmseeg-access` is a tested Python package for a public TMS-EEG dataset (OpenNeuro
ds008037: 123 subjects, 479 TMS runs). Analysts get a simple API down to epochs around each pulse, a
DuckDB catalog of every recording and 301,143 pulse markers, quality checks with a clear record for each
issue, a de-identification step, MATLAB export, and an HTML report.

**Design choices.**
- **Report, never repair.** Checks record what was seen, where, the rule and a suggested action. Doubled
  markers stop epoching until the analyst opts in, and that choice is saved with the epochs.
- **Metadata everywhere, signal where needed.** The catalog covers all subjects from text and headers.
  Signal is 3.85 GB of the release's 107.81 GB, and a check that couldn't run counts as coverage, not a
  pass.
- **Keep sources apart.** Sidecar, header and signal values stay in separate columns, because comparing
  them is the point. Published and observed protocol values are stored separately too.
- **Verify, don't assume.** Downloads are checked against release hashes, and one script regenerates all
  the evidence. The numbers in the docs trace to saved files, and an independent audit checked them.

**What the checks found.** There are 250 issues from 19 rules. The headlines:
- 243,139 of 301,143 markers are duplicates under 2 ms from the previous one. 240,801 are in one run,
  and the other 57 affected runs hold 2,338.
- Pulses are 3.023 s apart at the median. The preprint says 4 to 6 s, and only 13 of 57,525 gaps fit.
- 20 of 40 signal-checked runs still show a pulse artifact or a very large channel, and 13 reach 1,000 uV.
  All 13 record interpolation in their headers, so the header can't tell you which runs are clean.
- The sidecars' stated reference channel carries signal in all 40 runs, so the stated reference is wrong.
- `TRIGGER`, usually a flat channel, is typed as EEG in 392 runs, which explains the 62 versus 63 split.
- 47 runs form a separate processing batch, visible in their headers and channel tables.
- Per-subject stimulation dose isn't published, so it can't be joined.
- Also useful: all 432 available site codes match their labels, and sidecars agree with headers on all
  479 runs.

These are observations. I don't know their causes, and the authors may have simple explanations. Checking
changed my own conclusions: the artifact isn't only frontal, smoothing at markers proves timing but not
that a pulse happened, and a median across channels missed artifacts on a few channels.

**Limits.**
- Signal checks cover 10 subjects chosen to include problems, so their rates don't generalise.
- The placebo timing test covers sub-001 only. Time base checks cover all 479 runs.
- Sizes are in the data as stored, whose true reference is unknown. Some large values may be bad
  electrodes, not pulse artifact.
- It targets one dataset, and another would need a new protocol file and reader changes.
- MATLAB opening is untested (no MATLAB here). Round trips were verified in Python.
- CI hasn't run on GitHub, only in a clean clone on Windows. It wasn't tested on a Mac.
- It's not Keller lab data, which isn't public, and it contains no iTBS. De-identification isn't a HIPAA
  certification.

**Next steps.**
1. Ask the authors about spacing, dose, the true reference, `*_nibs` files and the 0.1 s marker pairs.
2. Run signal checks on all subjects.
3. Separate bad electrodes from pulse artifact.
4. Test the exports in MATLAB and EEGLAB.
5. Add a BrainVision reader, the format in the lab's `Analysis-Physiology` pipeline.

## To say out loud

"I built a Python package that gives analysts clean access to a public TMS-EEG dataset, from a simple API
down to epochs around each pulse, with a SQL catalog of every recording and about 300,000 pulse markers.
It treats data quality as a first-class output: every issue records what was observed, where, the rule
and a suggested action, and it never silently fixes anything. Those checks found things you can't see in
the file names, such as pulse spacing that disagrees with the published protocol, and runs with large
artifacts even though their headers say the artifact was removed. I verified the timing against the raw
headers with a placebo test on one subject, and an independent audit of my own numbers caught a metric
that was missing real problems, so I fixed it and reran everything. It's the kind of work that replaces a
hand-kept list of bad recordings with something repeatable."
