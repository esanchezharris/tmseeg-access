# Audit record

The finished project went through a final review on 2026-11-03. All of it was done with Claude Code: the
claim trace and the recalculation were separate AI review agents, not people, and they didn't see how the
work had been built.

## What was done

| Pass | Method | Result |
|---|---|---|
| Claim trace | Every number and factual claim in the docs traced to a saved file or to the code | About 350 claims, 29 defects, 8 of them wrong |
| Recalculation | Headline findings recomputed from the raw files with new code, before reading the project's code, except one arithmetic check | Counts agreed. Three claims changed. Values are hand-copied into `results/independent_recomputation.json`, and the agent's scripts aren't kept |
| Source check | Published values and lab-code claims read again in the original preprints and repository | Values confirmed. One new finding, the FPz reference. Quotes in `results/published_values.json` |
| Real runtime | Exports opened and re-saved in GNU Octave 11.3.0 and EEGLAB 2026.0.0 | One real bug. Results in `results/octave_roundtrip.json` |
| Full rebuild | All evidence rebuilt from a clean commit, and again after the fixes | Row order and build time weren't stable. Row order is fixed, and build time is no longer quoted |

## What it changed

**Code**
- EEGLAB exports held false events: 22 extra in the 120-epoch sample, because raw-time annotations were
  read as positions in the joined epochs. The Python round trip only compared signal, so it passed.
- New rule `pulse.mixed_marker_codes`: 49 runs carry more than one trigger code.
- New rule `signal.frozen_signal`: sub-071 prefrontal holds 20,181 samples with most channels unchanged.
  The saturation rule couldn't see this, because the signal isn't held at an extreme.
- New rule `sidecar.reference_differs_from_published`: sidecars say FCz, the preprint says FPz.
- Example queries no longer present unchecked runs as usable, and tied rows now have a fixed order.

**Claims corrected**
- "10 of 13 show no interpolated samples" isn't supported. Roughness can't establish it, because a large
  interpolated curve still reads as rough. They're now described as having no sample in the window
  smoother than baseline.
- "58,004 distinct pulses" is a count of markers, and some are not pulses.
- "13 of 57,525 gaps" depends on the counting rule. It's 15 between kept markers, and 1 in runs with no
  duplicates (`spacing_variants` in `results/hand_checks.json`). The conclusion doesn't change.
- 13 runs reach 1,000 uV on the average across pulses. It's 14 if sub-134 parietal is measured on its
  120 code 128 markers, and 17 if a single pulse is enough.
- "The stated reference is wrong" went beyond the evidence at the time. The FPz evidence now supports a
  narrower claim: the sidecars and the channel tables' `reference` column say FCz, the preprint says FPz,
  and FCz isn't flat in the 40 signal-checked runs.
- A catalog build of "about 3 s" was a best case, and build time is no longer quoted.
- Average referencing ranges from making the worst channel 14.6 times smaller to about 1.07 times larger.
  It made it larger in 2 of 13 runs.

## Still open

- Nothing was run in MATLAB itself, and `struct2table` in `docs/matlab.md` can't run in Octave.
- The 439 runs without local signal have had no signal checks.
- A third review agent then rechecked the rewritten docs against the rebuilt results: about 300 claims, no
  headline number wrong, 22 wording and traceability defects, all then corrected. That last round of
  corrections was not reviewed again.
- These stayed unresolved in the recalculation, and are not reported as findings elsewhere: 4 of the 10
  runs with no smooth sample couldn't be classified, and the 47-run group may use a wider interpolation
  window, which
  rests on sub-125 only.
