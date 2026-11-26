## 05 · Build ICT Test Sequence

This node authors the ICT test sequence: one row per test or operation, in the canonical order the engine runs them. Set the limits for the numeric tests - R-GND in Ω, voltage in V, clock in Hz - and a test passes when the measured value is inside range.

### Before you start

- Node 04 is locked; it supplies the instrument channels and the rail capture.
- Node 02's parse result seeds the first sequence, so opening the node shows rows instead of an empty table.

### Steps

1. Open the node and read the generated order: `Power On DUT` → rails capture (Start) → voltage rows → clock rows → GPIO drive/read/toggle → rails capture (End) → `Power Off DUT`.
2. Double-click a row to edit its test point, limits, timeout and channel.
3. Keep the run order with `Move Up` / `Move Down`.
4. Press `Reset to generated order` to return to the canonical sequence.
5. Work through both tables until every row carries its limit.
6. Press `Lock & Next: 07 · Apply & Save Yaml`.

### Check before you lock

- The sequence starts with `Init Instruments` and ends with `Reset Instruments`.
- Exactly one power-on and one power-off row; a re-power needs its own YAML.
- R-GND rows run before the power step, voltage and clock rows after it.
- The rails capture brackets the measurement block, so the waveform belongs to one run.

### If the node refuses to lock

- `Not complete: no test rows left - nothing to run` - rebuild the sequence with `Reset to generated order`.
- `Not complete: the sequence must start with Init Instruments …` - move `Init Instruments` back to the first row.
- `Not complete: the sequence must end with Reset Instruments …` - move `Reset Instruments` to the last row.
- `Not complete: one power-on per sequence …` / `Not complete: one power-off per sequence …` - keep exactly one of each.
- `Not complete: <step> runs on the wrong side of the power step` - move that row before / after `Power On DUT`.
