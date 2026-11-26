## 07 · Apply & Save Yaml

The end of the chain. The node previews the generated YAML read-only, shows the validation state, and writes the project file - `Apply & Save Yaml` writes in place, `Save as new yaml` writes a new file. There is no `Next`.

### Before you start

- Nodes 05 and 06 are locked (both are prerequisites of this node).
- Know whether the project file is overwritten or saved as a new file.

### Steps

1. Read the `Draft YAML preview (read-only):` box.
2. Check the status line: `Validation: OK`, or `Validation: <n> error(s)` with the findings listed underneath.
3. Check `Target file:` - the draft name is derived from the product identity.
4. Press `Apply & Save Yaml` in the panel, or `Apply_Save yaml` in the footer - both run the same validation and write.
5. Press `Save as new yaml` to write a named copy instead of overwriting.
6. Use `Export MTK ICT Excel Sheet…` when the plan has to be reviewed in Excel.

### Check before you lock

- Validation passes; a failed one lists every finding and nothing is written.
- A test run in progress makes the panel read-only, so configuration cannot change under a running test.
- The plan version in the page header is copied into the YAML and bumps with each iteration (`Draft` → `Final`).

### If the node refuses to lock

- `Validation: <n> error(s)` - the list under it names each finding; fix them in the owning node and press again.
- `Apply failed: <reason>` - the file could not be written; the message carries the reason.
- `Save failed: <reason>` - the chosen target could not be written; pick another path.
