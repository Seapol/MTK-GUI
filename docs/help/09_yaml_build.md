# Yaml Build Page

The **Yaml Build** tab is where a test project is authored. It renders
one horizontal flow of seven nodes; clicking a node opens its panel in
its own dialog:

```text
01 Design Input -> (02 Parse nets for ICT  ||  03 Firmware Config)
-> 04 Equipment Config
-> (05 Build ICT Test Sequence  ||  06 Build FCT Test Sequence)
-> 07 Apply & Save Yaml
```

The bar is linear because a bar can only run left to right: the two
parallel pairs (02/03 and 05/06) are drawn in sequence. Gating follows
that diagram - both members of a pair must be locked before the next
node opens. Nodes the project's ICT / FCT selection switches off stay
grey and open read-only, so what they hold can still be audited.

The page carries the flowchart only. There is no YAML preview pane, no
in-page footer and no export strip: the YAML is written by
`Apply & Save Yaml` on node 07 and by the File menu.

![The seven-node Yaml Build flow](images/04_yaml_build.png)

A loaded project also shows what a capacity-limited plan looks like on
stage 07: the shipped `examples/ict_96624` plan has 82 power nets against
the 80-point front end and 692 parsed Control-IO candidates against the
24 DIO lines, and node 07 reports it (`+668 over capacity`,
`validation: NOK (incomplete rows)`) instead of dropping the extra nets
quietly.

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
- **Gating follows the padlocks, not the clock**: node 01 unlocks both
  02 and 03; either branch (02 parse or 03 firmware) unlocks 04
  Equipment Config; 04 unlocks 05 and 06 together; 05 or 06 unlocks 07.
  An FCT-only project is still legal - the ICT nodes grey out instead of
  blocking the chain, and an ICT-only project greys 03 and 06 the same
  way.
- **Unlocking cascades forward**: releasing a node also releases every
  later node, so a changed upstream fact always re-opens the modules it
  feeds.
- **`Next` and `Save Draft` live inside the dialog** (M124 / M127). Node 01
  hands over to 02, 02 and 03 both hand over to 04, and 04 to 05. Node 07
  is the end of the chain and shows no `Next`; `Save Draft` is on every
  node window and writes the current (possibly incomplete) values to the
  draft YAML without validating them.
- **The page carries the flowchart only** (M127): the old `Cancel` /
  `Save Draft` / `Next` footer and the top `Export to Excel` strip are
  gone. The workbook export stays in `File -> Export Config Workbook...`.
- **Cards are colour-coded and badged** (M128): grey = not used by the
  project (the ICT / FCT switch in node 01 skips it), pale yellow = still
  to be configured, green = locked and complete. The bottom-right badge
  reads `Empty`, `Edited` or `Completed` / `Unused` to match. Lock states
  travel with the project - reopening a YAML restores the padlocks.
- **Node 04 Equipment Config is a launcher, not a tab strip** (M131): the seven modules -
  `Instruments`, `Power On/Off DUT`, `R-GND & Voltage`, `Clock`,
  `Power Rails`, `Fixture (ATE)` and `Peripherals` - are large cards; each
  opens its own dialog with its own layout. `Instruments` is the wide
  banner card and gates the other six: they stay grey with a `LOCKED` badge
  until `Check availability` has run. Every card carries a live badge
  (`CHECKED` / `NOT CHECKED`, net and clock counts, the PSU setting) so the
  node can be read without opening anything.
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
| **Route B** `ICT Excel Spreadsheet (Traditional)` | a traditional ICT Excel | imports a prepared per-net test list |
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

Every edit is written to the model as you type it; node 07 writes the
project YAML.

## Node 02 - Parse nets for ICT

![Parse Nets for ICT](images/07_yaml_parse_nets.png)

The panel shows the parsed netlist as **two tables side by side** (M129):

- **Parsed Nets** (left) - every net the classifier recognised as a test
  category: `Power`, `SE Clock` or `GND`.
- **Other Nets** (right) - everything parked in `Other`, i.e. not testable
  as it stands.

Both tables share the same columns - `Net Name`, `Category`, `Sub-type`,
`Test Point`, `Nominal`, `Limits`, `Confidence` - and each row carries a
category dropdown, so a net can be moved to another bucket without
re-parsing. `Move Up` / `Move Down` keep the rows in the order you want
them consumed.

The summary line under the tables is the audit trail for this file; on
the 96624 reference board it reads:

```text
Power 82 · SE Clock 20 · GND 4 · Other 2124 · skipped 0 rows
```

Those five numbers add up to the netlist (2 230 here: `82 + 20 + 4 + 2124`,
with `skipped` counting rows the parser refused). Every number is recomputed
from the file on each parse, so a colleague's build is comparable straight
away.

`Parse Nets…` picks the netlist (Route A), re-reads it and refills both
tables. Two behaviours worth knowing:

- nets on DNP parts leave the `Power` bucket once a BOM is applied, because
  they are not testable on the fixture - the same netlist gives `Power 82`
  on its own and a lower power count with the BOM;
- the parse result is written into the model as it is produced, so node 05
  seeds from the latest parse the moment it opens.

## Node 03 - Firmware Config

Node 03 configures **how** the FAT and OOBE images are flashed. It
configures only: there is no execution state, no output tail, no Abort
and no timeout here - flashing happens later, inside the FCT run.

Two slots, FAT on top and OOBE below. Each slot has its own `Enable`
checkbox and picks one method:

| Method | Fields | Verdict |
|---|---|---|
| `CLI command` | `Terminal`, `Command`, `Pass keyword` | the run parses the terminal output: the pass keyword found = PASS, the fail keyword found or nothing = FAIL |
| `3rd-party GUI tool` | `Tool path`, `Arguments`, `Prompt` | the tool window opens; the operator answers the Go / Stop prompt, and that answer is the verdict |

- **The pass keyword is the only judge that counts** (M130): the slot
  used to ask for the same text twice, so a typo in one box made the row
  unpassable. There is one `Pass keyword` field now, and one `Fail
  keyword` that is optional.
- **An unchecked slot greys every field of that slot** (M130c) - text
  boxes, dropdowns, radios and the hint lines - so a half-configured slot
  never looks editable. Both slots unchecked is legal; the footer then
  says `no firmware slot enabled - FCT will run without flashing`.
- A disabled slot collapses to `{enabled: false}` in the YAML, so the
  engine skips it instead of flashing defaults.

The FCT run's two flashing rows (`STEP_FLASH`, see node 06) read this
configuration; changing a terminal or a path here changes the run.

## Node 04 - Equipment Config

Node 04 is the rack map: seven modules, each a large card, each opening
its own dialog with a layout built for that module (M131) - no shared
seven-tab strip any more.

| Card | What it configures |
|---|---|
| `Instruments` (wide banner) | the DAQ973A mainframe, its DAQM908A / DAQM907A modules and the other rack instruments; the `Check availability` button |
| `Power On/Off DUT` | main input source, PSU limits, fixture relay, operator prompts |
| `R-GND & Voltage` | the 80-point two-wire resistance and voltage rows |
| `Clock` | the three clock rows and their windows |
| `Power Rails` | the 12 rails, their order and setpoints |
| `Fixture (ATE)` | probe ports and the control signals |
| `Peripherals` | Wi-Fi / BT / router / debug probe / display and the rest of the production peripherals |

- **`Instruments` gates the other six**: until `Check availability` has
  run, the six stay grey with a `LOCKED` badge and refuse to open.
- **Every card carries a live badge** - `CHECKED` / `NOT CHECKED`, `3
  NETS`, `2 CLOCKS`, the PSU setting, `RECORD-ONLY` - so the node can be
  read without opening anything.
- **Each module dialog is its own layout**: two grouped sections plus a
  capacity card for `Instruments`, four grouped sections for
  `Power On/Off DUT`, a full-width table for `R-GND & Voltage`, `Clock`
  and `Power Rails`, a two-column form for `Fixture (ATE)` and a 2x2
  check grid for `Peripherals`. The dialogs are resizable and remember
  their instance, so reopening a module returns to the same window.

## Node 05 - Build ICT Test Sequence

This node opens the ICT step editor - one row per test or operation, in the
canonical order the engine runs them:

```text
Power On DUT -> rails capture (Start) -> voltage rows -> clock rows
-> GPIO drive/read/toggle -> rails capture (End) -> Power Off DUT
```

Rails capture brackets the measurement block, so the waveform belongs to one
run. Each row carries its test point, limits, timeout and channel; double
click a row to edit it. The dialog re-seeds itself from an existing sequence,
so loading a saved plan and re-opening node 05 shows the stored rows instead
of an empty table.

The Test Work Flow table is a read-only result view of this sequence:
double clicking an ICT row opens the same editor, so there is exactly one
place to change a step.

## Node 06 - Build FCT Test Sequence

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


## Node 07 - Apply & Save Yaml

The end of the chain. It shows the generated YAML read-only and the
validation state, then offers exactly two buttons in a fixed order:

- **`Apply & Save Yaml`** - validate, write the project YAML in place.
- **`Save as new yaml`** - write a new file instead of overwriting.

Node 07 shows no `Next`. If validation fails, the findings are listed and
nothing is written. A run in progress puts the panel read-only with a
notice, so configuration cannot change under a running test.

## Saving, validating, exporting

- **`Apply & Save Yaml`** on node 07: validate, apply to the model, write
  the project YAML in place (see node 07 above).
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
