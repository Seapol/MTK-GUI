## 06 · Build FCT Test Sequence

This node authors the FCT test sequence: message tests (console Wait → Send → Capture with a Pass / Fail verdict), firmware flashing, and RF (Wi-Fi / BT) - mostly third-party CLI or a manual dialog confirm.

![FCT test sequence](images/16_01_fct_sequence.png)

### Before you start

- Node 04 is locked; nodes 05 and 06 unlock together from it.
- Node 03 is configured when the sequence carries flashing rows.
- Know which console channel each message row talks to.

### Steps

1. Press `Add Step` and pick the step type, or press `Advanced…` for the full editor (its `Load Template` writes a starter sequence for `Bare Metal DUT`, `Linux DUT` or `Wifi_Scan (Host<->DUT)`).
2. Select a step and fill the `Selected step` form: `Name`, `Type`, `Channel`, `Command`, `Expect pass`, `Expect fail`, `On fail`.
3. For a `FLASH` step, also pick `Slot` (`fat` / `oobe`) and `Flash mode`.
4. Remove a step with `Delete`; reorder with `Move up` / `Move down`.
5. Give every console row its judge - `Expect pass` for the message that must be found, `Expect fail` for the one that must not.
6. Press `Lock & Next: 07 · Apply & Save Yaml`.

### Check before you lock

- Every console row names what it expects; a row without a judge cannot pass and the save is blocked with that reason.
- A row declared as a setup row is skipped instead of judged - it never claims a PASS.
- An expected-absence row needs its end line as evidence.
- Duplicate step names and unknown dependencies are refused.

### If the node refuses to lock

- `step name must not be empty` - give the selected step a name.
- `duplicate step names in the sequence` - rename one of the two steps.
- `step '<name>': CLI_RUN requires a command` (or `FLASH … requires a command`) - fill `Command`.
- `step '<name>': unknown dependency '<name>'` - point the dependency at an existing step or remove it.
