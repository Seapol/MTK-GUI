# Yaml Build Page

The **Yaml Build** tab is where a test project is authored. It has one
layout, top to bottom:

```text
Plan version: [ field ]                       <- header
01 Design Input -> 02 Parse nets for ICT -> 03 Channel Allocation
-> 04 Build ICT Test Work Flow Sequence -> 05 Build FCT Test Work Flow Sequence
[ Power Nets | Clock Nets | Control IO Nets ]  <- embedded tables
rows: power=.. power_rails=../.. clock=.. gpio=.. - validation: ..
```

Five nodes on a single row, each connected to the next; the Channel
Allocation tables sit directly below them; the status line under the tables
reports the four counts and the validation state. There is no YAML preview
pane any more - the YAML is written by `Apply_Save yaml` inside each node
dialog and by the File menu.

![Yaml Build page with the shipped 96624 demo plan loaded](images/04_yaml_build.png)

The shot above is the shipped `examples/ict_96624` demo plan, so it also shows
what a capacity-limited plan looks like: 82 power nets against the 80-point
front end and 692 parsed Control-IO candidates against the 24 DIO lines. The
footer says so (`+668 over capacity`, `validation: NOK (incomplete rows)`)
instead of dropping the extra nets quietly.

## How the nodes behave

- **Left-click a node** to open its dialog. Each dialog validates its own
  fields: invalid input keeps the dialog open with the reason, and a node
  is never half-saved.
- **Right-click a node** for `Enable` / `Disable`, plus `Enable All` /
  `Disable All`. A disabled node renders gray with a `Disabled` badge,
  keeps its parameters, and is skipped by the flow, the validation and the
  YAML it generates.
- **A star** on the node means it has been applied and validated at least
  once in this project. Stars persist with the project.
- **Every node dialog has a padlock** (M128) on its right-hand action row,
  showing the current state: `Unlock` while the module is open,
  `Locked` once it has been checked. Clicking it runs the full validation
  behind a foreground progress bar, so a long check never freezes the
  window; a failed check lists the findings in a message box and leaves
  the node unlocked. Locking means *this module's input is finished and
  still valid* - only then does `Next` become available.
- **Gating follows the padlocks, not the clock**: node 02 opens once node
  01 is locked; 03 and 04 open once the parse is locked; 05 needs 02 and
  04 locked, 06 needs its ICT counterpart, and 07 needs both build nodes.
  An FCT-only project is still legal - the ICT nodes grey out instead of
  blocking the chain.
- **Unlocking cascades forward**: releasing a node also releases every
  later node, so a changed upstream fact always re-opens the modules it
  feeds.
- **`Next` and `Save Draft` live inside the dialog** (M124 / M127). Node 01
  hands over to 02, node 02 to 04 (the Channel Allocation card runs
  automatically on the way and says so in the Event Log), node 04 to 05.
  Node 07 is the end of the chain and shows no `Next`; `Save Draft` is on
  every node window and writes the current (possibly incomplete) values
  to the draft YAML without validating them.
- **The page carries the flowchart only** (M127): the old `Cancel` /
  `Save Draft` / `Next` footer and the top `Export to Excel` strip are
  gone. The workbook export stays in `File -> Export Config Workbook...`.
- **Cards are colour-coded and badged** (M128): grey = not used by the
  project (the ICT / FCT switch in node 01 skips it), pale yellow = still
  to be configured, green = locked and complete. The bottom-right badge
  reads `Empty`, `Edited` or `Completed` / `Unused` to match. Lock states
  travel with the project - reopening a YAML restores the padlocks.
- **Every node dialog is resizable** (M124): minimize / maximize and
  free resize are enabled, the width you see is a *minimum*, long
  content scrolls both ways instead of being clipped, and form fields
  stop growing at a sensible cap - a wide window no longer stretches a
  four-character field across the whole row.
- **Node 01 shows the file name, not the full path** (M124): SPF / NET /
  BOM / workbook rows display the base name, with the full path in the
  tooltip.
- **File -> Close Yaml empties every node** (M124): the project values
  are replaced by the schema defaults, so opening a node right after a
  close never shows the previous project's data.
- **Close Yaml also clears every lock and badge** (M128): the flowchart
  returns to the untouched state. Loading another YAML clears the old
  values first, then fills every node from that file - including the
  padlock state it carries in `yaml_build.locks`.

## Node 01 - Design Input

![Design Input panel](images/06_yaml_design_input.png)

Three cards, top to bottom: **Product Information**, then **Design Files
for ICT** and **Pre-Configure for FCT** side by side.

**Product Information** is a two-column grid, so the rows use the width
without stretching a short field across the dialog:

| Row | Left | Right |
|---|---|---|
| 1 | `Product Part #` (editable) | `Core ID` (editable) |
| 2 | `FSW Revision` | `700 HW Revision` |
| 3 | `Batch #` | detail of the customized / deviation batch |

Both revisions are dropdowns: `Rev A` ... `Rev H` plus `Customized ...`.
Picking `Customized ...` asks for the text; cancelling keeps the previous
choice. A value loaded from an older YAML is added as its own item and
stays verbatim (e.g. `1.0.3` or `Rev C-2`), so an old project never gets
silently rewritten.

Each card has its own `Enable` checkbox. Clearing it turns the whole card
grey - labels, radios, buttons, dropdowns and text - not just the
controls, so a disabled card is unmistakable. The `Enable` checkbox
itself stays clickable.

Three route choices inside **Design Files for ICT**, stacked top to
bottom:

| Route | Input | What it does |
|---|---|---|
| **Route A** `SPF + NET + BoM` | Allegro Smart PDF + netlist (+ BOM) | the normal path: node 02 classifies the nets |
| **Route B** `ICT Excel Spreadsheet` | a traditional ICT Excel | imports a prepared per-net test list |
| **Route C** `MTK ICT Excel Sheet` | the four-sheet workbook written by this tool | round trip for stations that review plans in Excel |

Only one route is live at a time: the two you did not pick - radio label
and its body alike - grey out. **Switching route clears every imported
ICT file**, so a Route A project can never carry a Route B workbook into
node 02; the Event Log says so and you import again for the new route.

Route A fields:

- `Import SPF...` - Allegro Smart PDF only. The title block fills
  **Project Part #** and **Core ID**; both stay editable.
- `Import NET...` - **load only**. The netlist is kept in memory and parsed
  by node 02, never by the import.
- `Import BOM...` - optional and non-blocking. The status line reports
  `records / DNP / conflicts / warnings`. The BOM matters: DNP parts make
  their nets untestable (see node 02).
- **Batch #** - a batch containing `Production` marks the plan as
  production (OEE counts it); anything else stays engineering.

**Pre-Configure for FCT** holds `DUT Board Software` and the list of
supported FCT test types, split into `Standard test steps` (Console
serial, Serial file transfer, SSH SFTP, Message dialogs) and
`FCT-specific test steps` (Wi-Fi, Bluetooth). `Select all` and
`Select none` are shortcuts; selecting nothing is a legal configuration.

The board software picks the default tick set: `linux` ticks everything,
`bare_metal` ticks `Console serial` and `Message dialogs`, `slave_daughter`
ticks `Message dialogs` only. A project YAML that already stores a list -
including an empty one - wins over those defaults.

Press **Apply_Save yaml** to apply and write the project YAML.

Press **Apply_Save yaml** to apply and write the project YAML.

## Node 02 - Parse nets for ICT

![Parse Nets for ICT](images/07_yaml_parse_nets.png)

`Parse Nets for ICT` classifies every net into three views:

- **Parsed Nets** - net, test point, category (`Power` / `Clock` /
  `Control IO` / `GND` / `Other`), confidence, input-rail flag, sub-class.
  A dropdown lets you move a net to another category.
- **Filtered Nets** - nets removed by the rule set or by DNP, with the
  reason and a category dropdown so a net can be brought back.
- **GND integrity** - one line under the tables; more than one reference
  ground raises a warning instead of being silently accepted.

`Parsed Nets` and `Other Nets` are laid out **side by side** (M129): the
nets that feed the ICT sequence sit on the left, the ones the rule set
parked in `Other` on the right, so the classification reads left to right
instead of two stacked tables with empty space between them. Each table
keeps its own horizontal scrollbar for the wide column set.

`Edit Net Classification Rules` opens the regex rule set (power tree
patterns, clock patterns, exclude patterns, DNP handling). Two behaviours
worth knowing:

- the counters above the tables are `classified + filtered` for this file,
  so the number is reproducible;
- importing a BOM changes the power count, because nets on DNP parts drop
  out. On the 96624 reference board that is `power=82` from the netlist
  alone against `power=49` with the BOM.

The result is written into the model only when the dialog is applied.

## Node 03 - Channel Allocation

The node is a navigation card with an `Auto assign` button: clicking it runs
the automatic allocation and fills the embedded tables below; no dialog
opens. Three tabs follow the resource pools:

- **Power Nets** - test point, `R-GND Min limit (ohm)`, `Nominal (V)`,
  `Lower limit (V)`, `Upper limit (V)`; the voltage columns become the
  voltage rows of node 04, the resistance column becomes the `R-GND` rows.
- **Clock Nets** - test point, expected frequency, window.
- **Control IO Nets** - the 24 DIO lines, drive / read / toggle.

Rows are editable in place (dropdown-only where a fixed choice applies). The
status line under the tables counts them:

```text
rows: power=82 power_rails=12/82 clock=20 gpio=24 - validation: OK
```

`power_rails=12/82` means 12 of the 82 power nets are armed for the rails
capture. Anything that does not fit a pool is reported as over capacity and
becomes Do-Not-Test when the sequence is built - visible, never silent.

## Node 04 - Build ICT Test Work Flow Sequence

This node opens the ICT step editor - one row per test or operation, in the
canonical order the engine runs them:

```text
Power On DUT -> rails capture (Start) -> voltage rows -> clock rows
-> GPIO drive/read/toggle -> rails capture (End) -> Power Off DUT
```

Rails capture brackets the measurement block, so the waveform belongs to one
run. Each row carries its test point, limits, timeout and channel; double
click a row to edit it. The dialog re-seeds itself from an existing sequence,
so loading a saved plan and re-opening node 04 shows the stored rows instead
of an empty table.

The Test Work Flow table is a read-only result view of this sequence:
double clicking an ICT row opens the same editor, so there is exactly one
place to change a step.

## Node 05 - Build FCT Test Work Flow Sequence

Same editor shape, FCT content: `Init Instruments`, `Fixture Clamp Down`,
`Power On/Off DUT`, `Delay`, console rows (`Console_serial` / `_ssh` /
`_cli`, `Message`), file transfer rows (`Serial: Push file to DUT`,
`SSH SFTP: Push/Pull`), RF rows (`Wifi_Scan`, `Wifi_Ping`, `Wifi_Iperf`,
`BT_RSSI`, `BT_Pair`, `BT_Tone`) and `STEP_FLASH` for the two firmware
stages. `Load Template` writes a starter sequence in place for
`Bare Metal DUT`, `Linux DUT` or `Wifi_Scan (Host<->DUT)`.

Every console row must name what it expects (`Expected must be found`,
`Unexpected must not be found`); a row without a judge cannot pass, and the
save is blocked with that reason.

## Saving, validating, exporting

- **`Apply_Save yaml`** in every node dialog: validate, apply to the model,
  write the project YAML in place.
- **`Save Draft`** in every node dialog (M127): snapshot the current node
  values - no validation, no file is deleted - and the window reports the
  draft path. An unfinished node can be parked this way and finished later.
- **File -> Save Yaml (current file)** (`Ctrl+S`) writes the current file;
  **File -> Save Yaml As... (current file)** (`Ctrl+Shift+S`) writes a named
  copy; **File -> Close Yaml** clears the page.
- An empty sequence raises `No Test Items - Save anyway?`; answering **No**
  keeps you in the editor.
- **Plan version** in the header is copied into the YAML and bumps with each
  iteration (`Draft` -> `Final`).
- **File -> Excel** holds the review paths: export the config workbook,
  import a traditional ICT plan, import / export the MTK ICT sheet.

## Where to go next

- Chapter `15 · Example Build of ICT Test Case` walks the whole page on the
  shipped 96624 plan, with the real numbers for each step.
- Chapter `16 · Example Build of FCT Test Case` does the same for the
  FRDM-IMX93 FCT plan.
