## 04 · Equipment Config

Node 04 is the rack map: seven module cards assign instrument channels - R-GND / voltage to the DAQ, clocks to the counter, the DUT to the console - and configure the production peripherals.

### Before you start

- The rack is connected and powered; the `Instruments` card gates the other six.
- Nodes 02 and 03 are locked (both are prerequisites of this node).

### Steps

1. Open the `Instruments` card - the wide banner - and press `Check availability`.
2. Open `Power On/Off DUT` and pick the main input source, the PSU limits and the operator prompts.
3. Fill `R-GND & Voltage` (the 80-point two-wire rows) and `Clock` (the three clock rows and their windows).
4. Review `Power Rails` (the 12 rails, their order and setpoints).
5. Open `Fixture (ATE)` for the probe ports and control signals.
6. Configure `Peripherals`: Wi-Fi / BT / router / debug probe / display and the rest.
7. Read each card's live badge instead of opening it: `CHECKED` / `NOT CHECKED`, `3 NETS`, `2 CLOCKS`, the PSU setting, `RECORD-ONLY`.

### Check before you lock

- The instrument check has run, and a power-on source is selected.
- Every power and clock row is allocated to a channel or marked not tested.
- Adapter power needs the fixture relay channel or both prompts.
- The rail rows have their AI channel and no duplicate assignment.

### If the node refuses to lock

- `Not complete: instrument check not run` - open `Instruments` and press `Check availability`.
- `Not complete: power-on source not selected` - open `Power On/Off DUT` and pick the source.
- `Not complete: <n> power nets not allocated` / `Not complete: <n> clock nets not allocated` - assign the missing channels or mark those rows not tested.
- `Not complete: adapter power needs the fixture relay or a prompt` - set the relay channel or both prompts.
