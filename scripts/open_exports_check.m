function open_exports_check(export_dir, eeglab_dir, output_json)
% Open the exports the way a MATLAB or EEGLAB user would, and record what was seen.
%
% Runs in GNU Octave and is written to run in MATLAB too. Each step records an error instead of
% stopping, so one failure doesn't hide the others. scripts/octave_roundtrip.py compares the
% values written here with the original epochs in Python.

report = struct();
report.runtime = runtime_name();
stem = 'sub-001_parietal_epochs';
report.mat = guarded(@() check_mat(fullfile(export_dir, [stem '.mat'])));
report.metadata = guarded(@() check_metadata(fullfile(export_dir, 'metadata.mat')));
report.eeglab = guarded(@() check_eeglab(eeglab_dir, export_dir, stem));

handle = fopen(output_json, 'w');
fprintf(handle, '%s\n', jsonencode(report));
fclose(handle);
end


function name = runtime_name()
if exist('OCTAVE_VERSION', 'builtin')
    name = ['GNU Octave ' OCTAVE_VERSION()];
else
    name = ['MATLAB ' version()];
end
end


function out = guarded(step)
try
    out = step();
    out.ok = true;
catch failure
    out = struct('ok', false, 'error', failure.message);
end
end


function out = check_mat(path)
% The first block is the "Plain MATLAB" example from docs/matlab.md.
s = load(path);
erp = squeeze(mean(s.data_uv, 1));
figure_handle = figure('visible', 'off');
plot(s.times_s * 1000, erp');
xlabel('Time from pulse (ms)');
close(figure_handle);
provenance = jsondecode(s.provenance_json);

out.data_size = size(s.data_uv);
out.erp_size = size(erp);
out.times_first_s = s.times_s(1);
out.times_last_s = s.times_s(end);
out.sampling_rate_hz = s.sampling_rate_hz;
out.channels = reshape(cellstr(s.channels), 1, []);
out.event_ids = reshape(cellstr(s.epochs_table.event_id), 1, []);
out.provenance_fields = reshape(fieldnames(provenance), 1, []);
out.channel_mean_uv = reshape(mean(mean(s.data_uv, 3), 1), 1, []);
out.trial_mean_uv = reshape(mean(mean(s.data_uv, 3), 2), 1, []);
out.largest_abs_uv = max(abs(s.data_uv(:)));
end


function out = check_metadata(path)
m = load(path);
names = fieldnames(m.metadata);
columns = cell(1, numel(names));
for i = 1:numel(names)
    value = m.metadata.(names{i});
    gaps = 0;
    if isnumeric(value)
        gaps = sum(isnan(value(:)));
    end
    columns{i} = struct('name', names{i}, 'class', class(value), 'rows', numel(value), ...
                        'gaps', gaps);
end
out.columns = columns;
% Octave has no table type, so the struct2table line in the docs can only run in MATLAB.
out.struct2table_available = exist('struct2table') > 0;
if out.struct2table_available
    table_rows = height(struct2table(m.metadata));
    out.table_rows = table_rows;
end
end


function out = check_eeglab(eeglab_dir, export_dir, stem)
addpath(eeglab_dir);
eeglab('nogui');
EEG = pop_loadset('filename', [stem '.set'], 'filepath', export_dir);
EEG = eeg_checkset(EEG);

out.nbchan = EEG.nbchan;
out.pnts = EEG.pnts;
out.trials = EEG.trials;
out.srate = EEG.srate;
out.xmin = EEG.xmin;
out.xmax = EEG.xmax;
out.events = numel(EEG.event);
out.event_positions = mod([EEG.event.latency] - 1, EEG.pnts);
out.event_epochs = [EEG.event.epoch];
out.labels = {EEG.chanlocs.labels};
out.channel_mean_uv = reshape(mean(mean(double(EEG.data), 2), 3), 1, []);
out.largest_abs_uv = max(abs(double(EEG.data(:))));

% Write it back from EEGLAB, so Python can read a file EEGLAB itself produced.
pop_saveset(EEG, 'filename', 'resaved_by_eeglab.set', 'filepath', export_dir, ...
            'savemode', 'onefile');
out.resaved = true;
end
