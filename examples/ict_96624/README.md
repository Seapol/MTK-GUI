# ICT example — 96624, built by Route A (Parse nets for ICT)

This is the reference ICT plan for board **CORE 96624 / part A-96624** as
Route A produced it, untouched by hand. Load it in the GUI to see what a
complete ICT sequence built from a netlist looks like, then compare your own
plan against it.

## What is in the file

| Item | Count |
|---|---|
| ICT rows | 34 (31 enabled, 3 disabled with a reason) |
| Power rails captured by DAQ AI | 12 |
| Route A buckets | 82 power / 20 clock / 24 control IO / 4 GND / 1 432 filtered |
| Raw nets in the netlist | 2 231 |

The three disabled rows are the nets for which neither the SPF nor any
engineer sheet gave a limit:

- `Power Voltage - VBAT_SENSE`
- `Power Voltage - VCC_OSC_AUXCLKIN`
- `Power Voltage - VDD2_LP5X`

They stay in the plan because coverage is visible, and each carries a
`comment` saying why it is off. A limit-less row reports **TBD**, and TBD fails
the ICT stage, so an unmeasurable item must never gate a run — but it must
stay traceable. That is the production rule this example is meant to show.

## Verified result

Run in Virtual mode on 2026-11-25 (`scripts/build_96624_ict_demo_yaml.py`
reproduces it): `Overall Result: PASS`, *all 31 enabled ICT steps PASS*.
Impedance rows pass on the 1.5 Ω short floor; voltage rows on the
auto-filled ±5 % window; the three clock rows on 32.768 kHz ±50 ppm.

Known cosmetic point, visible on purpose: the three limit-less rails carry
`nominal_v: 0.0`, so the rails chart draws them flat until a limit is
authored. That is the same gap as the disabled rows, drawn instead of
written.

## How to load it

1. Log in as **Supervisor** in **Virtual** mode.
2. `File → Load Project` (or `Yaml Build → Load current yaml`) and pick
   `A-96624_ICT_Demo_v1.0.1.yaml`.
3. Open **Test Work Flow** and press **Run**. Expect PASS with the three
   disabled rows showing their comment.

The YAML also carries the parsed netlist under `imported.net.raw`, so the
Parse Nets tab reopens with the same data without the original `.net` file.

## Rebuilding it

The netlist itself is not in this repository (customer data, and `projects/`
is ignored). With `projects/96624/NET-96624_A.net` present, rebuild with:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python scripts/build_96624_ict_demo_yaml.py
```

Pins, classification and limits come from `parse_testable_nets` +
`build_allocation`; nothing in this example was typed by hand except the
N5747A setpoints (12.0 V / 3.0 A), which a plan must declare because a
`Power On DUT` row is a passive state carrier.
