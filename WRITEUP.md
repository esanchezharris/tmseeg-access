# TMS-EEG data access toolkit: writeup

**What it does.** `tmseeg-access` is a tested Python package for a public TMS-EEG dataset (OpenNeuro
ds008037: 123 subjects, 479 TMS runs). Analysts get a simple API down to epochs around each pulse, a
DuckDB catalog of every recording and 301,143 pulse markers, quality checks with a clear record for each
issue, a de-identification step, MATLAB export, and an HTML report.

**Design choices.**
- **Report, never repair.** Checks record what was seen, where, the rule and a suggested action. Doubled
  markers stop epoching until the analyst opts in, and that choice is saved with the epochs.
- **Metadata everywhere, signal where needed.** The catalog covers all subjects from text and headers.
  Signal is 3.99 GB of a 109.8 GB release, and a check that couldn't run counts as coverage, not a pass.
- **Keep sources apart.** Sidecar, header and signal values stay in separate columns, because comparing
  them is the point. Published and observed protocol values are stored separately too.
- **Verify, don't assume.** Downloads are checked against release hashes. Pulse timing was confirmed with
  a placebo test. Every number in the docs comes from a saved file.

**What the checks found.** There are 208 issues from 18 rules. The headlines:
- 243,139 of 301,143 markers are duplicates under 2 ms from the previous one, and one run has 240,923.
- Pulses are 3.023 s apart at the median. The preprint says 4 to 6 s, and only 13 of 57,525 gaps fit.
- 18 of 40 signal-checked runs still contain the TMS artifact, and 8 peak over 1,000 uV even though their
  headers record that it was interpolated. The header can't tell you which runs are clean.
- A flat `TRIGGER` channel is typed as EEG in 392 runs, which explains the 62 versus 63 channel split.
- 47 runs form a separate processing batch, visible only in their headers.
- Per-subject stimulation dose isn't published, so it can't be joined.
- Also useful: all 432 site codes match their labels, and sidecars agree with headers on all 479 runs.

These are observations. I don't know their causes, and some may have simple explanations the authors
could give. Hand-checking also corrected my own early conclusions: the artifact isn't only frontal, and
smoothing at markers proves the timing but not that a pulse happened.

**Limits.**
- Signal checks cover 10 subjects chosen to include problems, so their rates don't generalise.
- The artifact's size is per channel in the recorded reference. Average referencing would shrink much of
  it, but not in every run.
- It targets one dataset. Another would need a new protocol file and reader changes.
- MATLAB opening is untested (no MATLAB here). Round trips were verified in Python.
- CI hasn't run on GitHub, only in a clean clone on Windows. It wasn't tested on a Mac.
- It's not Keller lab data, which isn't public, and it contains no iTBS. De-identification isn't a HIPAA
  certification.

**Next steps.**
1. Ask the authors about spacing, dose, `*_nibs` files and the 0.100 s marker pairs.
2. Run signal checks on all subjects.
3. Add an `average_reference` view of the artifact check.
4. Test the exports in MATLAB and EEGLAB.
5. Add a BrainVision reader, the format in the lab's `Analysis-Physiology` pipeline.

## To say out loud

"I built a Python package that gives analysts clean access to a public TMS-EEG dataset, from a simple API
down to epochs around each pulse, with a SQL catalog of every recording and about 300,000 pulse markers.
It treats data quality as a first-class output: every issue records what was observed, where, the rule
and a suggested action, and it never silently fixes anything. Those checks found things you can't see in
the file names, such as pulse spacing that disagrees with the published protocol, and runs that still
contain the TMS artifact even though their headers say it was removed. I confirmed the pulse timing with
a placebo test instead of assuming it, and every number in the docs traces back to a saved output file.
It's the kind of work that replaces a hand-kept list of bad recordings with something repeatable."
