# Using the data in MATLAB

**Status:** the round trip is tested by reading the exported files back in Python
(`results/matlab_roundtrip.json`). MATLAB isn't installed on the build machine, so the MATLAB and
EEGLAB code below has not been run. If you run it, please report anything that doesn't work.

## Export

```bash
uv run tmseeg-access export --subject sub-001 --site parietal --output exports --metadata
```

This writes:

| File | Contents |
|---|---|
| `sub-001_parietal_epochs.mat` | Epochs, times, channels, the per-epoch table and provenance |
| `sub-001_parietal_epochs.set` | The same epochs for EEGLAB |
| `sub-001_parietal_epochs_epochs.csv` | The per-epoch table, which a `.set` file can't carry |
| `sub-001_parietal_epochs_provenance.json` | The choices made when cutting the epochs |
| `metadata.mat` | The joined metadata table |

Add `--exclude-channels TRIGGER` for subjects that have that channel. Add
`--on-duplicate keep_first` for runs with doubled markers, once you've reviewed them.

## Plain MATLAB

Signal is in microvolts, as trials x channels x samples.

```matlab
s = load('sub-001_parietal_epochs.mat');
size(s.data_uv)                      % trials x channels x samples

erp = squeeze(mean(s.data_uv, 1));   % channels x samples
plot(s.times_s * 1000, erp');
xlabel('Time from pulse (ms)');

s.epochs_table.event_id              % the marker behind each epoch
jsondecode(s.provenance_json)        % how the epochs were cut
```

## EEGLAB

```matlab
EEG = pop_loadset('filename', 'sub-001_parietal_epochs.set');
```

## Metadata

Each column is a field. Numbers are numeric with `NaN` for gaps. Text is a cell array, with empty
text for gaps.

```matlab
m = load('metadata.mat');
t = struct2table(m.metadata);
```
