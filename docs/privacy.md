# Privacy: what `deidentify` does and does not do

**This step is not a certification of HIPAA compliance.** It removes specific fields from a copy of
the data. Whether a dataset is de-identified under HIPAA is decided by Safe Harbor review of the 18
identifier categories, or by a qualified expert's determination, and by your institution's privacy
office. Neither has happened here, and this tool can't replace them.

ds008037 is already public and de-identified by its authors. It's used to show the step working on
realistic files. The fields found in it were not sensitive patient data, but they do show where
identifying text can hide.

## Why this exists

A dataset can have tidy, anonymised file names and still carry identifying text inside its headers.
In this release (`results/header_provenance.json`):

- Absolute file paths appear in the `.set` `filepath` field of 479 of 479 TMS runs.
- The original file path appears in `comments` and in `history` in 432 runs.
- `chaninfo` holds a path through a user's home folder in 432 runs, which exposes a local username.
- Original filenames include a study code in 432 runs (`results/hand_checks.json`).

None of this is visible in the BIDS file names. Anyone auditing only the file names would miss it.

## What it does

`tmseeg-access deidentify --output <new folder>` writes a copy. The source is never changed, and the
command refuses to write inside the source or into a folder that isn't empty.

| Where | Action |
|---|---|
| `.set` free-text fields: `comments`, `history`, `filepath`, `subject`, `group`, `session`, `condition` | Blanked |
| Any other `.set` string that looks like a path, email address or date | Blanked, wherever it sits in the structure |
| JSON sidecars: institution name, address and department, device serial number, station name, software versions | Removed |
| `*_scans.tsv` `acq_time` | Shifted 30 to 365 days into the past, by the same amount for all of a subject's files |
| `participants.tsv` | Filtered to chosen subjects. Columns you name are dropped |
| `*_electrodes.tsv`, `*_coordsystem.json` | Kept, unless you pass `--drop-head-geometry` |
| `.fdt` signal | Copied byte for byte, then verified by SHA-256 |

**Date shifts** come from a keyed hash of the subject label, so intervals within a subject survive.
With no key, a random one is used and discarded, so shifts can't be reversed. Don't keep a key with
the data.

**After copying**, it scans every output `.set`, `.json` and `.tsv` file again for anything that still
looks like a path, address or date, and writes `deidentification_log.json`. The log holds counts, never
the removed values. The scan only finds these patterns, so a clean scan doesn't prove a file is free of
identifying text.

Unfinished downloads (`.part`, `.tmp`) are never copied, because they could carry an unscrubbed header.

## Verified on real data

Running it on sub-001 (`results/deidentify_demo.json`) changed these fields across the 4 TMS `.set`
files and left all 4 `.fdt` files identical to the source. No header still held suspicious text
afterwards, and epochs loaded from the copy matched the original exactly at all 4 sites.

The scan flagged `dataset_description.json`. That's a deliberate kind of false alarm: the match is the
citation link for the dataset's own paper, which the scan reads as a path. It's reported, not removed,
so a person can decide.

## What it does not do

- **The signal itself is not altered.** EEG can carry individually identifying patterns. Nothing here
  addresses re-identification from brain activity.
- **Head geometry stays by default.** Digitised electrode positions describe a person's head shape.
  Use `--drop-head-geometry` to remove them.
- **Demographics stay by default.** Age, sex, education and smoking status can identify someone in
  combination, especially in a small group. There is no check for small groups (k-anonymity), and
  ages are not capped.
- **Subject labels are not re-coded.** The original numbering is kept, and this release's labels match
  the numbers in its original filenames.
- **Free text is only pattern-matched.** A name typed into a note won't match a path, email or date
  pattern unless it's in a field that is always blanked. Behavioural files and event values are not
  scanned for it.
- **Some files aren't scanned.** `datacite.yml`, `README` and `CHANGES` are copied as they are. They
  name dataset authors, not participants.
- **File dates.** The copy's `.set` files carry the time this step ran in their internal header.
- **MRI defacing is out of scope.** This release includes no MRI.
- **It only knows this layout.** It handles EEGLAB files and BIDS sidecars. Other formats, such as
  BrainVision or EDF headers, would need their own handling. EDF in particular stores patient fields.

For real health data, use this as one step in a reviewed process, on approved systems, with your
privacy office involved. Don't run it on protected data on a personal machine.
