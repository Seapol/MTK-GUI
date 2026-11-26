## 03 · Firmware Config

This node configures **how** the FAT and OOBE images are flashed - it only configures. Flashing happens later, inside the FCT run (node 06), and the two flashing rows there read this configuration.

### Before you start

- Have the flash method ready: a `CLI command` with its terminal tool, or a `3rd-party GUI tool` with its executable path.
- Decide which images this project flashes: FAT on top, OOBE below.

### Steps

1. Tick the slot's `Enable` checkbox.
2. Choose `CLI command` or `3rd-party GUI tool`.
3. For `CLI command`, fill `Terminal`, `Command` and `Pass keyword`; `Fail keyword` is optional.
4. For `3rd-party GUI tool`, fill `Tool path`, `Arguments` and `Prompt`.
5. Repeat for the other slot when both images are flashed.
6. Press `Lock & Next: 04 · Equipment Config`.

### Check before you lock

- The `Pass keyword` is the only judge that counts: the pass keyword found in the terminal output = PASS, the fail keyword found or nothing = FAIL.
- A `3rd-party GUI tool` row opens the tool and the operator's Go / Stop answer is the verdict.
- An unchecked slot greys every field of that slot, and a disabled slot collapses to `{enabled: false}` in the YAML, so the engine skips it instead of flashing defaults.
- Both slots unchecked is a legal configuration.

### If the node refuses to lock

- There is no refusal message on this node: the footer reads `no firmware slot enabled — FCT will run without flashing` and locking accepts that configuration.
- A CLI slot without a pass keyword cannot judge a run - go back and fill `Pass keyword` before the FCT run.
