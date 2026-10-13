# Channel Allocation Page

The **Channel Allocation** tab is the dedicated per-category
allocation editor: three dropdown-only tables assign the instrument
channel resources to the nets parsed by the Yaml Build block 02
(Parse nets for ICT). The page sits next to the **Yaml Build** tab
and shares its project model.

![Channel Allocation](images/05_channel_allocation.png)

## Data Source and Model Link

- **Data source**: the Parse Nets result (the `Parse Nets for ICT`
  module of the Yaml Build page) - the single data source. The hint
  line under the buttons states exactly this; all configuration
  cells are dropdown-only.
- **Model injection**: the page shares the same project model with
  the Yaml Build page. The tables are written into the model's
  `channel_allocation` section (persisted to the project YAML) and
  into the restart-safe project store.
- **Refresh**: the tables re-sync with the current parse result on
  every Yaml Build page entry and after every parse - the saved
  configuration of unchanged nets is kept, new nets are appended,
  removed nets are dropped.
- **Autosave**: leaving the Yaml Build tab persists the configuration
  automatically; opening the ICT sequence card or publishing syncs
  the tables into the model silently first.

**Note:** empty tables mean there is no parse result yet - run
block 02 `Parse nets for ICT` on the Yaml Build page first.

## Page Layout (embedded in the Yaml Build page)

- The tables sit directly below the five workflow cards; the
  `Auto` allocation is triggered by the **03 · Auto-Channel
  Allocation** card (2026-10-13 - the standalone buttons are gone;
  applying to the YAML is owned by the preview pane's
  `Apply to Yaml` button).
- The muted hint line naming the data source.
- The tab widget with `Power Nets` / `Clock Nets` / `GPIO Nets`.
- The summary line at the bottom, for example
  `rows: power=12 clock=3 gpio=8 - validation: OK`. With resource
  conflicts the line turns red and appends the detail, e.g.
  `- CONFLICT: DAQM908A CH101 -> VDD_3V3, VDD_1V8`.

## Power Nets Tab

Columns:

- `Net` - net name from the parse result (read-only).
- `Test point` - dropdown of the net's member pins: a `TP` probe
  pin when the members carry one, otherwise the member pins; the
  fixed `TP1` - `TP4` fallback applies only when a net has no
  dot-pins at all.
- `Impedance` - DAQM908A sense channel for the 2-wire ohm
  measurement: `DAQM908A #1 CH101` - `CH140` and `DAQM908A #2
  CH201` - `CH240`.
- `Power rails` - U2355A analog input for the up-sequence capture:
  `U2355A AI01` - `AI12` (the hardware offers 16 inputs, the GUI
  provides 12 for a balanced sampling rate).
- `Voltage` - DAQM908A sense channel for the DCV measurement (the
  same pool as `Impedance`).

There are no `Instrument` / `Channel` / `Status` columns by design -
the resource is implicit in the channel name.

## Clock Nets Tab

- `Net` - net name (read-only).
- `Test point` - member-pin dropdown.
- `SE Clock Hz` - the capture resource: `DAQM907A TOT`,
  `U2355A CTR0` or `U2355A CTR1`.
- `Frequency band` - read-only, hardware-derived from the chosen
  resource: `DAQM907A TOT` maps to `0 ~ 100 kHz`, the two U2355A
  counters map to `0.1 Hz ~ 6 MHz`. A legacy free-text band resets
  to the unset state on reload.

## GPIO Nets Tab

- `Net` - net name (read-only).
- `Test point` - member-pin dropdown.
- `DIO Channel` - one of the 16 DAQM907A digital channels
  (`DAQM907A DIO01` - `DAQM907A DIO16`). The U2355A DIO stays
  reserved for the fixture control.

There are no `Digital Input` / `Digital Output` columns - the
drive / read / toggle behavior comes from the test definitions, not
from the allocation.

## Dropdown Rules

- Every configurable cell is a **dropdown** - free text is
  impossible.
- Unset cells show the placeholder `—`.
- Single-choice combos auto-show their only option (e.g. a net with
  exactly one member pin) - a row never hides an unset state behind
  a displayed value.
- Legacy values that are no longer offered by the resource pool
  reset cleanly to `—` (never a hidden stale value).
- Empty or legacy project files load blank without error.

## Auto Allocation

`Auto` fills the **Power** and **Clock** tables top-down:

1. **Test point**: the best probe pin of the net (a `TP` pin
   preferred, else the first member pin).
2. **Power rows**: sequential DAQM908A sense channels - `Impedance`
   and `Voltage` share the SAME channel (the 2-wire ohm then DCV
   reuse) - plus the next free `U2355A AI` channel for
   `Power rails`.
3. **Clock rows**: sequential `SE Clock Hz` resources; the
   `Frequency band` auto-fills from the hardware mapping.
4. Beyond the pool capacity the row stays unset - that net cannot
   be tested; adjust the affected rows manually afterwards.

**Note:** the GPIO DIO channels are deliberately NOT auto-assigned -
configure them manually.

## Row Validation

A row is OK when every configurable cell of its kind is set:

- power: `Test point` + `Impedance` + `Power rails` + `Voltage`
- clock: `Test point` + `SE Clock Hz` (the band auto-fills)
- gpio: `Test point` + `DIO Channel`

The bottom summary shows `validation: OK` only when every row of
every table is complete; otherwise it reads
`NOK (incomplete rows)`.

## Do-Not-Test Rules

- A net **without a fully allocated channel set is automatically
  Do-Not-Test**: only allocated nets reach the ICT Test Work Flow
  sequence builder of the Yaml Build page. A power net needs all
  three resources (`Impedance` + `Power rails` + `Voltage`) before
  its tests are generated; a clock net needs `SE Clock Hz`; a GPIO
  net needs `DIO Channel`.
- Nets flagged Do Not Test in the Parse Nets panel (block 02) keep
  that flag; the flags persist with the project.
- Rows the pool could not serve (Auto overflow) stay unset and are
  therefore not testable until you assign resources manually.
- Nets you filtered or moved in the block 02 tables never appear
  here at all.

## Channel Conflicts

One instrument resource used by **more than one net** is a conflict
and turns the summary line red:

- The conflict check runs per resource pool: DAQM908A (the
  `Impedance` + `Voltage` pool), `U2355A AI` (the `Power rails`
  pool), `SE Clock` and `DAQM907A DIO`.
- One net using the same channel for `Impedance` AND `Voltage` is
  the normal Auto behavior - NOT a conflict.
- The summary line shows the conflicts in red as soon as they
  exist, e.g. `- CONFLICT: DAQM908A CH101 -> VDD_3V3, VDD_1V8`.

## Persistence (Apply to Yaml)

1. The tables persist into the model automatically: on Yaml Build
   tab leave, before the ICT sequence card opens and before every
   publish (project YAML `channel_allocation` section plus the
   project store, an Event Log line records the row counts).
2. The right-pane preview's `Apply to Yaml` button commits the full
   model into the YAML document (and offers the file save).

**Warning:** Operator accounts cannot modify the YAML configuration
- the allocation dropdowns stay disabled (view only).

## Table Behavior

- Click a column header to sort the whole table by that column;
  clicking the same header again toggles ascending / descending.
- Columns are user-draggable with per-column minimum widths; the
  `Net` column grows first but only up to a cap, so it can never
  starve the other columns.
- Your manual column widths persist with the project and are
  restored on reopen; a window resize re-distributes the widths per
  the adaptive rules.

## Common Issues

- Empty tables - no parse result yet: run block 02
  `Parse nets for ICT` on the Yaml Build page.
- `Channel Conflict` on apply - one resource is assigned to more
  than one net; the dialog names the exact pool, channel and nets.
- `validation: NOK (incomplete rows)` - work through the rows with
  unset `—` cells, or run `Auto` for the Power / Clock tables
  first.
- A parsed net is missing - it was filtered or moved to Filtered
  during the parse; restore it in the block 02 panel (pick a real
  category) and re-open this tab.
- The `Frequency band` cell shows `—` although a clock is picked -
  the saved value predates the resource pool and was reset; pick
  the `SE Clock Hz` resource again.
