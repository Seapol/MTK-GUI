# Route A vs Route B — Parse Quality on 96317 and at Scale on 96624

Date: 2026-11-25 · Question: how accurate is **Route A** (*Parse nets for ICT*,
built from the netlist) against **Route B** (the engineer's hand-analysed ICT
Excel), taking Route B as the reference?

## 1. The two routes, same board (96317 / FRDM-IMXRT700)

| | Route A — parse nets | Route B — engineer sheet |
|---|---|---|
| Input | `projects/96317/NET-96317_A.net` | `96317_FRDM-IMXRT700_SPREADSHEET_revA_for production(1).xlsx`, sheet `RESULTS` |
| Method | name/pin-shape rules over the netlist | block heading decides the class (impedance / voltage / frequency) |
| Power nets | **7** | **16** |
| Clock nets | **1** (`DMIC_CLK`) | **1** (`XTAL 32.768KHZ …` at `TP1.1`) |
| Control-IO / GPIO | 5 | — |
| Other testable-but-unmeasured | 24 (unclassified) | — |
| Filtered out | 31 (I2C / UART / GND, by the Exclude Parse Nets regex) | 2 rows skipped (`Y1` 24 MHz, `Y2` 16 MHz — `Y-designator is not probeable from MTK`) |
| Test point carried by the row | present on 5 of 7 power nets | present on all 16 rails and the clock |
| Limits | from rules/templates (nominal + tolerance) | from the sheet: `> 10 ohm`, min/nominal/max per rail (e.g. `DCDC_3V3` 3.135 / 3.3 / 3.465) |
| Gate | none | impedance-vs-voltage power sets must match (`gate_ok = True`) |

Route B's full list (the reference): `SYS_5V0` (TP35.1), `DCDC_3V3` (TP37.1),
`P3V3_SDA` (TP93.1), `PMIC_LDO4_3V3_OUT` (TP51.1), `MCU_1V8` (TP96.1),
`MCU_AO1V8` (TP97.1), `PMIC_LDO1_1V8_AO` (TP54.1), `PMIC_LDO2_1V8_OUT`
(TP53.1), `PMIC_SW4_1V8_OUT` (TP50.1), `VDD1V8` (TP99.1), `WL_1V8` (TP62.1),
`MCU_1V2` (TP101.1), `PMIC_LDO3_1V2_OUT` (TP52.1), `VDD1` (TP102.1), `VDD2`
(TP103.1), `VDDN` (TP104.1).

Route A's power list: `5V_SDA_PSW`, `5V_USB0_OTG` (TP89.1), `CODEC_1V8`,
`DCDC_1V0` (TP87.1), `DCDC_1V8` (TP88.1), `DCDC_3V3` (TP37.1), `DC_5V_IN`
(TP72.1).

## 2. What the two YAMLs would hold

Neither 96317 project has a built YAML on disk, so the comparison is made at
the parse layer — the layer that fully decides what the build step can emit:

- Route A (this excerpt): 7 power × (R-GND + voltage) + 1 clock = **15 rows**,
  plus the 5 control-IO rows if the DIO pool is enabled.
- Route B (engineer sheet): 16 power × (R-GND + voltage) + 1 clock = **33 rows**,
  the count the production sheet itself implies (its rev history quotes
  "20 mins" for the whole sequence).

The only built artifact in the tree is 96624's Route A YAML
(`projects/96624/A-96624_ICT_Demo_v1.0.1.yaml`, 34 rows) — that one is
covered in `ICT_96624_Route_A_prep_2026-11-24.md`.

## 3. Name-level join

| Bucket | Count | Detail |
|---|---|---|
| Found by both | **1** | `DCDC_3V3` — same net, same class, same TP (`TP37.1`) |
| In Route B, invisible to Route A | **15** | `SYS_5V0`, `P3V3_SDA`, `MCU_1V8`, `MCU_AO1V8`, `PMIC_LDO1_1V8_AO`, `PMIC_LDO2_1V8_OUT`, `PMIC_SW4_1V8_OUT`, `PMIC_LDO4_3V3_OUT`, `VDD1V8`, `WL_1V8`, `MCU_1V2`, `PMIC_LDO3_1V2_OUT`, `VDD1`, `VDD2`, `VDDN` |
| In Route A, not in Route B | **6** | `5V_SDA_PSW`, `5V_USB0_OTG`, `CODEC_1V8`, `DCDC_1V0`, `DCDC_1V8`, `DC_5V_IN` |

**The 15 names are absent from the netlist itself**, not misclassified by the
parser. `NET-96317_A.net` is a 74-line excerpt: 70 nets total, of which only
`DCDC_3V3` is one of the engineer's rails. Everything the engineer measured on
the PMIC / DDR / WLAN domains (`TP50–TP104`) has no line in that file. So Route
A's recall on this pair is **1/16 = 6 %**, and that number measures the input
file, not the algorithm.

The 6 Route A-only rails are real supply nets of the same board that the
production sheet chose not to test (`DCDC_1V0`, `DCDC_1V8` have TPs; `DC_5V_IN`
has `TP72.1`; `5V_USB0_OTG` has `TP89.1`; `5V_SDA_PSW` and `CODEC_1V8` carry
no test point). Extra findings are not necessarily errors — but the last two
cannot be measured without you adding a TP.

## 4. Route A at production scale (96624 / S32N79, complete netlist)

`NET-96624_A.net`, 111 KB, **2 230 nets**:

| Class | Count | Share |
|---|---|---|
| Power | 82 | 3.7 % |
| SE clock | 20 | 0.9 % |
| Control IO | 24 | 1.1 % |
| Other testable, unclassified | 668 | 30.0 % |
| GND (reference) | 4 | 0.2 % |
| Filtered | 1 432 | 64.2 % — 1 178 by the Exclude Parse Nets regex, 254 differential pairs |

82 + 20 + 24 = **126 measurable objects**, i.e. **208 numeric rows** once every
power net gets both R-GND and voltage (82 × 2 + 20 + 24). The rack pools then
bound how many of those actually ship: the 96624 demo YAML ends at 34 ICT rows
(12 rails on U2355A AI, 3 single-ended clocks, 24 DIO), and the rest of the
82 power nets stay unallocated until the fixture grows.

## 5. Precision audit — where Route A is wrong on 96624

Checked every questionable entry against its pin list in the netlist.

| Net | Route A says | Pin evidence | Verdict |
|---|---|---|---|
| `SPI3_SENT_SEL_1V8` | power rail | `R1165.2 U150.4 U152.15 U154.15` — one series resistor into three IC select pins, no decoupling | **false positive**: a 1.8 V-level *select strap*, not a supply; measuring it as power would FAIL a good board |
| `VBAT_SENSE` | power rail | `R424.2 U63.64` — resistor into one sense input | **false positive**: a sense line, not a rail |
| `EXTAL` | clock | `R909.1 R910.2 U50.R65` — two resistors and one SoC pin, no driver/crystal | **suspect**: no clock source on the net; needs confirmation |
| `EXTAL_OPT` | clock | `R910.1 R920.1 R923.1` — resistors only | **suspect**: an option strap |
| `XTAL` | clock | `R900.1 R901.1 U50.R67` | **suspect**: series/strap network, not a crystal |
| `XTAL_OPT` | clock | `R891.1 R895.1 R900.2` | **suspect**: option strap |
| `XTAL_XA` / `XTAL_XA-2` | 2 clocks | `Y5.1`, `Y4.1` — two real crystals | correct, and correctly kept separate |
| `DUT_AUXCLKIN` / `DUT_AUXCLKOUT1` | clocks | driven from / to `U50` | correct |

Precision: power **80/82 ≈ 97.6 %**, clock **16/20 = 80 %** if the four
resistor-only entries are counted as noise; 100 % if they turn out to be
buffered clocks (the netlist cannot tell a buffer output from a resistor).

On 96317 the same audit gives 5 of 7 power nets TP-backed, 2 without
(`5V_SDA_PSW`, `CODEC_1V8`) — Route A proposes the net, the fixture has to
provide the point.

## 6. What this means for the two routes

- **Route B is the better spec, and it is small**: 16 rails × 2 tests + 1 clock
  = 33 measurements, every one TP-backed with hand-set limits, and a built-in
  consistency gate. That is what "engineer analysed" buys: the test point
  exists and the limit is argued.
- **Route A is a good first pass on a complete netlist**: 98 % power precision,
  correct separation of differential pairs and grounds, and it produces things
  a hand sheet often forgets (the 24 control-IO straps, the second crystal).
  It cannot invent test points, it takes limits from templates, and its clock
  bucket needs an eye because a "clock" name is not a clock driver.
- **Do not score Route A against a truncated NET.** 96317's 70-net excerpt
  makes recall look like 6 %; on the complete 96624 file the same rules yield
  126 measurable objects. The first question to ask of any "Route A is
  inaccurate" report is *how many nets did the file contain?*

## 7. Three rule fixes worth doing (each is a small, testable change)

1. **Signal-suffix demotion.** A net whose name carries a rail voltage *and* a
   control token (`SEL`, `EN`, `RST`, `INT`, `MODE`, `CS`, `BOOT`) is a strap,
   not a supply — `SPI3_SENT_SEL_1V8` is the case that proves it. Would also
   catch the `*_SEL_1V8` family on other boards.
2. **Sense-net demotion.** A `*_SENSE` net fed only through one resistor into
   one IC pin (`VBAT_SENSE`) is a measurement input, never a rail.
3. **Clock-source check.** A clock row needs a driver: a `Y`/`X` designator,
   an oscillator/buffer output, or a SoC clock output pin. Resistor-only nets
   (`EXTAL`, `EXTAL_OPT`, `XTAL`, `XTAL_OPT`) should be dropped to "Other" with
   the reason recorded, or merged into the clock they feed.

Plus one workflow point, not a parser fix: a power row without a test point
should be flagged at allocation time (`no test point on the net — add a TP or
mark Do-Not-Test`), which is exactly how Route B keeps 16/16 clean.

## 8. Reproduce

```bash
cd <repo>
.venv/bin/python - <<'PY'
from mtkgui.ict.netparse.route_b import parse_results_sheet
from mtkgui.ict.netparse.parser import parse_nets_file
rb = parse_results_sheet("projects/96317/96317_FRDM-IMXRT700_SPREADSHEET_revA_for production(1).xlsx")
ra = parse_nets_file("projects/96317/NET-96317_A.net")
ra2 = parse_nets_file("projects/96624/NET-96624_A.net")
print(rb.summary()); print(ra.summary()); print(ra2.summary())
PY
```

Both files live outside git (`projects/` is ignored); they are staged on the
authoring machine only.
