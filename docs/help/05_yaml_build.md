# Yaml Build Page

The **Yaml Build** tab authors the test project: a fixed 12-stage
block workflow on the left and the live YAML preview on the right.
You work left-to-right: import the design data, parse the nets,
allocate channels, configure instruments, build the ICT / FCT
sequences, validate everything and export the plan YAML.

![Yaml Build page](images/04_yaml_build.png)

## Page Layout

- **Left pane - block flow**: the workflow stages as chained cards.
  Wide windows lay the cards out in wrapping rows; narrow windows
  fall back to a single column. The order is fixed and cannot be
  reordered.
- **Right pane - YAML Preview**: the effective YAML, directly
  editable (no Edit mode). The `Apply` button validates the text and
  commits valid changes into the model.
- **Top button row** (directly above the preview): `Import from
  Excel`, `Export to Excel` and `Apply` share one uniform width.
- The splitter default is 7 : 3; drag the divider as needed.

The page hint summarizes the rules: click a block to configure it;
right-click to Enable / Disable. Block 03 (`Configure Instruments`)
is the ONLY rack-ATE instrument editor - later blocks reference it
read-only; the validate block checks the full sequence and gates the
export block. Disabled blocks are grayed, skipped and kept out of
the effective YAML (their parameters are retained).

## Working with Block Cards

- **Left-click** (or double-click) a card to open its dedicated
  configuration dialog. Each dialog validates independently:
  invalid input keeps the dialog open with the error list, so a
  module save is always all-or-nothing.
- **Right-click** a card for `Enable` / `Disable` plus the batch
  actions `Enable All` / `Disable All`. Disabled cards render grayed
  with a dashed border and an explicit `Disabled` badge, keep their
  tooltip and parameters, and are skipped by the flow, the
  validation and the YAML generation.
- **Marks** (top-right of a card): a star means edited (the dialog
  was confirmed with OK); a check means the module passed the full
  validation. A failed validation keeps the star ("edited but not
  validated"). Marks persist with the project.
- Every field carries a hover tooltip with label, unit, range,
  choices, requirement and usage notes.

The cards in workflow order (the on-page numbering follows the
12-stage list: block 03 = `Configure Instruments`, the validate
block = 11, the export block = 12):

```
01 Design Input
02 Parse nets for ICT
   Build ICT Test Work Flow Sequence   (merged card for the
                                        rails / clocks / gpios
                                        modules = blocks 04/05/06)
03 Configure Instruments
   Configure Programmer/Debugger       (block 07)
   Configure Peripherals               (block 08)
   Build FCT Test Work Flow Sequence
11 Validate Full Test Sequence
12 Preview & Export YAML
```

## Block 01 - Design Input

![Design Input](images/06_yaml_design_input.png)

The entry point: import the schematic PDF and the netlist, fill the
product metadata. The card opens the unified Design Input panel.

- `Import SPF…` - loads an **Allegro Smart PDF** (`*.pdf` only).
  The file is read and the project info is auto-parsed: **Product
  ID** from the Core ID in the file name and **Project Part #** from
  the first-page drawing title. Both fields stay editable. Errors
  are reported with the exact reason (e.g. a scanned or vector-only
  PDF with no extractable text, an empty file).
- `Import NET…` - loads the netlist (`*.net`, `*.net.txt`, `*.txt`)
  **load only**: raw bytes into memory, no parsing and no structure
  analysis. The formal parse happens in block 02. The captions under
  the buttons show the imported files (`SPF:` / `NET:` with the path
  and file name).
- Metadata fields: `Product ID` (required), `Project Part #`
  (required - the only board-level part number source),
  `SW Version` / `HW Version` (optional, report metadata only) and
  the `Batch #` dropdown.

`Batch #` options: `EVT (Proto-1)`, `DVT (Proto-2)`, `PVT
(Pilot-1)`, `Ramp-up (Pilot-2)`, `MP (Production)`, `R&R
(Return&Rework)`, `Deviation (DRQ)` (opens a dialog for up to 3 DRQ
numbers) and `Customized` (opens a name dialog).

Steps:

1. Click the `Design Input` card.
2. `Import SPF…` - Product ID / Project Part # auto-fill; correct
   them if the drawing title differs.
3. `Import NET…` - the NET bytes are kept for block 02.
4. Fill SW / HW version and Batch #.
5. `OK` - the fields validate (Product ID and Project Part # are
   required) and the card gets a star.

**Note:** Product ID + Project Part # drive the plan file naming
(block 12) and the project identity, so they must be correct before
you publish.

## Block 02 - Parse nets for ICT

![Parse nets for ICT](images/07_yaml_parse_nets.png)

The formal netlist analysis. The panel consumes the NET file
imported in block 01 - without it you get
`no NET file loaded - import a NET file on the Design Input page
first`.

- `Edit Net Classification Rules` (left of the parse button) - edit
  the net name regex rules for Power / SE Clock / Differential pair
  with instant test, factory reset and save-time regex validation.
  GND is system-auto and never user-configured. User rules override
  the system defaults; an explicitly empty pattern suppresses the
  name-based default for that category. Saving re-runs the parse
  immediately.
- `Parse Nets for ICT` - runs the formal parse with live progress
  on the global status bar and Event-Log detail per step: format
  auto-detection (SPF / PSTXNET / NET), cleaning, parsing,
  classification, test-point selection and path-risk scoring.
- `Risk Thresholds` - configure the test path complexity score
  thresholds (factory defaults: score 0-3 Low / 4-6 Medium / 7-10
  High). The warning is advisory only and never blocks a channel
  assignment.

The parse sorts every net into the three ICT test objects:

- **Power nets** - supply rails (`VDD`, `VCC`, `nVn`, `VPRE`, ...).
- **Clock nets** - single-ended clock nets (`CLK`, `XTAL`, `OSC`,
  ...).
- **GPIO nets** - the remaining signal nets.

Plus **GND** reference grounds (measurement loop reference, default
Do Not Test) and the **Filtered Nets** table.

### Parsed Nets table

Columns `Net` / `Test Points` / `Category` / `Do Not Test`:

- **Net** - net name (read-only).
- **Test Points** - the net's member probe pins; the best candidate
  first, alternatives shown as `(+n alt)`.
- **Category** - dropdown with `Power` / `SE Clock` / `Signal` /
  `GND` / `Filtered`. Picking `Filtered` moves the net into the
  Filtered Nets table; the override survives re-parses.
- **Do Not Test** - checkbox. `Signal` and `GND` nets default to
  Do Not Test; an explicit toggle wins over the category default.

### Filtered Nets table

Columns `Net` / `Reason` / `Category`. A net lands here with a
reason when it is not an ICT test object:

- `reference ground (measurement loop)`.
- `differential pair (not an ICT test object)`.
- `no valid member pin (no test point)`.
- `excluded by Exclude Parse Nets regex`.

The `Category` combo defaults to `Filtered`; picking a real category
moves the net back into the Parsed Nets table.

**Note:** every net that exists in the NET file but not in the
imported SPF is treated as an Allegro auto-generated net: it is
classified as Signal and **locked Do Not Test** (a WARNING line
lands in the Event Log).

**Warning:** the parse fails hard on unusable input with
`no nets found - the file has no recognizable netlist content
(wrong file or unsupported format)`. Re-check the file imported in
block 01.

The **GND integrity** hint below the tables is advisory: a single
global reference ground reads OK, several distinct reference grounds
hint at a multi-point / segmented ground (review the star-ground
topology).

On `OK` the parse result becomes the single data source for the
Channel Allocation tables; the Do-Not-Test flags, the classification
rules and the risk thresholds persist with the project.

## Channel Allocation (workflow step)

Channel assignment happens on the dedicated **Channel Allocation**
tab - see the Channel Allocation chapter of this guide. In the
workflow it sits between the parse and the instrument configuration:

- Every parsed net lands in one of the three tables
  (Power / Clock / GPIO) and receives its instrument resources from
  dropdowns only.
- A net **without a fully allocated channel set is automatically
  Do-Not-Test**: only allocated nets reach the ICT Test Work Flow
  sequence builder.
- The allocation is a first-class part of the project YAML - the
  Yaml Build model carries it, and `Apply to YAML` switches back to
  this page.

## Block 03 - Configure Instruments

![Configure Instruments](images/08_yaml_instruments.png)

The only rack-ATE instrument editor of the workflow - and it
deliberately has **no** parameter fields: all instrument
configuration lives on the Equipment page. The panel lists every
rack instrument, always all of them regardless of configuration
state:

- `DAQ973A + 908A/907A`
- `N5747A DC Power Supply`
- `DMM (optional)`

Each row shows the connection status (`Connected` in green /
`Disconnected` in gray / `Error` in red) and one `Connect` /
`Disconnect` button; `Connect All` / `Disconnect All` operate on the
whole table. The buttons use the same connection kernel as
`Tools > Set All instruments`; in Virtual mode they report the
virtual result. Hovering a row shows the configured VISA address
(or `not configured yet`).

Steps: click the card, connect the instruments you need, `OK`. The
connection state mirrors to the Equipment page and the status-bar
LEDs.

## Build ICT Test Work Flow Sequence (Rails / Clocks / GPIO)

The merged card for the underlying `rails` / `clocks` / `gpios`
modules (blocks 04 / 05 / 06). It reuses the block 03 instrument
resources read-only and owns the ICT test case editing. Clicking the
card opens the **Build ICT Test Work Flow Sequence** dialog:

- One ICT test per row, auto-generated in the canonical order
  **impedance -> power rails (voltage) -> clock** from the parse
  result: per power net one `Static Impedance` and one
  `Power Voltage` test, per clock net one `Clock Hz` test. No
  standard operations here - they are added on the Test Work Flow
  page on `OK`.
- Columns: `Test Method` / `Net` / `Unit` / `Expected` / `Min` /
  `Max`.
- Buttons: `Auto` (regenerate the sequence), `Move Up` /
  `Move Down`, `Add` / `Remove` / `Edit` / `Duplicate`; double-click
  a row to edit it in the `ICT Test Item` dialog.
- The `ICT Test Item` dialog picks the `Test Method` first; the
  `Net` combo follows the method, the `Unit` auto-fills and
  `Expected` pre-fills from the net name (`P3V3_LDO` -> 3.3 V,
  `CLK_24M` -> 24 MHz). The expected value with the default
  tolerance derives `Min` / `Max` (power rails +/-5%, clock
  +/-50 ppm). `Static Impedance` has no expected value and no max -
  a lower limit only.
- Only nets **with an allocated instrument channel** are offered;
  unallocated nets are auto Do-Not-Test.
- `OK` merges the standard operations on the Test Work Flow page
  and offers the YAML save; the card gets a star.

**Note:** the `DAQ AI` method needs no net or limits here - the
power rails are already allocated in Channel Allocation; adding the
test row is enough.

### Underlying module parameters

The three underlying modules own the capture + sequence parameters
(also settable via `Import from Excel` or a hand-edited YAML
`Apply`):

```
rails   Power-On Voltage (V, 0-60, default 5.0)
        Current Limit (A, 0-12.5, default 1.0)
        Power-On Delay (ms, 0-60000, default 100)
        Power-Off Delay (ms, 0-60000, default 200)
        Power-Off Protection (default true)
        Rail Sequence - one "rail:delay_s" entry per line (required)
        Voltage Tolerance (%, 0-5, default 0.1)
        Impedance Min (Ohm, default 1.5)
        Sample Rate (Hz, 1-250000, default 1000)
        Pre-Trigger (s, default -0.5)
        Post-Trigger (s, default 6.0)
        Anomaly Policy (stop | warn, default stop)

clocks  Clock Definitions - one "name:freq_hz:tolerance_pct" per
        line (required)
        Stabilize Time (ms, 0-10000, default 100)
        Drift Detection (default true)
        Multi-Clock-Domain Check (default false)

gpios   Pin Groups - one "name:pin:mode:pull" per line (required)
        Level Threshold (V, 0-5, default 1.5)
        Exception Check Rules (default true)
```

The merged card shows `Enabled` when ANY of the three underlying
modules is enabled; the right-click Enable / Disable applies to all
of them.

## Configure Programmer/Debugger and Configure Peripherals

- **Programmer/Debugger**: `Protocol` (SWD / JTAG), `Speed` (kHz),
  `Timeout` (ms), `Flash Address`, `Retries`, `Log Level`. A debug
  resource, separate from the rack ATE instruments; it generates no
  test steps.
- **Peripherals**: DUT on-board peripherals - Wi-Fi SSID / password,
  Bluetooth MAC, UART baud, I2C address, SPI speed, ADC reference
  and the init sequence (one step per line). No test steps are
  generated.

## Build FCT Test Work Flow Sequence

The FCT panel has three tabs - `Console`, `Wi-Fi`, `Bluetooth` -
editing the `fct_test_config`. On `OK` the configuration is parsed
and validated, and the ordered FCT step list (console commands +
Wi-Fi + Bluetooth) is generated, wrapped with the setup and closed
by a final `FCT done` operator dialog. The generated cases replace
the FCT Test Cases table on the Test Work Flow page (each case
carries its full step marker) and the YAML save is offered.

**Note:** a project may be ICT only, FCT only, or both. An FCT
configuration with every tab disabled is valid and yields zero
cases.

**Warning:** an invalid FCT configuration blocks the dialog with
the error list (`FCT config parse failed: ...` or the validation
errors, up to 15 shown) - fix the listed problems before applying.

## Validate Full Test Sequence

![Validate Full Test Sequence](images/09_yaml_validate.png)

The cross-node global validation: resource conflicts, parameter
ranges and dependency violations (three checkboxes, all default
true). Confirming the block runs the validation over every enabled
module:

- Every module marked with a star that passes gets a **check**
  mark.
- A failure keeps the stars (edited but not validated), pops the
  error list (first 15) and logs the count to the Event Log.

**Warning:** validation must pass before the plan can be published -
fix the listed errors and re-run the validate block.

## Preview & Export YAML

The workflow exit. The block owns the export options:

- `Export Directory` (default `config/plans`) - project config
  folder for the exported YAML.
- `Include Disabled Modules` (default `false`).

The right-pane **YAML Preview** shows the effective YAML of the
enabled modules in the fixed workflow order. The editor is directly
editable:

1. Edit the YAML text.
2. Click `Apply` - the text is validated.
3. On PASS the changes commit into the model, the block cards
   refresh and the main window offers the file save (overwrite the
   current YAML or save to a new YAML file).
4. On FAIL the errors are marked in red and nothing is committed.

## Excel Import / Export

- `Export to Excel` writes all module parameters, thresholds,
  sequences, enable states and remarks to an `.xlsx` workbook
  (default name `YamlBuild_<project>.xlsx`).
- `Import from Excel` validates the whole workbook first: invalid
  rows abort the import with the exact row reasons (the Event Log
  lists the first failures, the dialog shows up to 20).

**Note:** Operator accounts cannot modify the YAML configuration -
the action row and the `Apply` button are disabled and the preview
stays read-only.

## Publishing: Draft / Final Plan YAML

Publishing builds the plan document (header + effective modules)
and requires **all enabled modules to validate**. The file name is
composed automatically from the Design Input - no manual input:

```
Draft: Plan_[Core ID]_[Project Part#]_build_draft_v.1.0.0.yaml
Final: Plan_[Core ID]_[Project Part#]_build_final_v.1.0.0.yaml

Example: Plan_IMXRT700_MTK12345_build_draft_v.1.0.0.yaml
```

- `Core ID` = Design Input `Product ID`; `Project Part #` = Design
  Input `Project Part #`. Characters outside letters, digits, `.`,
  `_` and `-` are replaced with `_`.
- The plan version defaults to `1.0.0`; the dynamic `built_with`
  build version is embedded in the YAML header (`plan` section) and
  in the archive copy names, keeping the canonical file names
  compliant.
- A `Final` plan carries `locked: true` in the plan header.
- The file is written to the standard plans directory and an
  **archive copy** is stored under `archive/yamlbuild/<project key>`
  with a timestamp - the audit trail survives restarts and project
  switches.
- The result dialog lists the file, the archive copy, the plan
  version and the build version.

**Warning:** publishing fails with `Design Input must provide Core
ID and Project Part # before building a plan file` when block 01 is
incomplete, and with the validation error list when any enabled
module is invalid.

## Common Issues

- `no NET file loaded - import a NET file on the Design Input page
  first` - block 02 needs the NET import from block 01.
- `no nets found - the file has no recognizable netlist content`
  - wrong file or unsupported format; re-import the correct
  netlist.
- `Design Input must provide Core ID and Project Part # ...` -
  complete block 01 before publishing.
- A card shows a star but no check - run the Validate block; only
  validated modules carry the check.
- Validation lists `module <name>: <field>: value required` - open
  the named block and fill the required field.
- The ICT sequence builder offers fewer nets than parsed - the
  missing nets have no allocated channel (auto Do-Not-Test) or are
  flagged Do Not Test; complete the Channel Allocation tables.
