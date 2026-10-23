# Hardware BoM

The bill of materials for building the reference test station:
instruments, peripherals, cables, accessories and the HOST PC.
Every item states whether it is **Must** (the factory plan cannot
run without it) or **Optional** (needed only when the product plan
uses that feature), and which tests or functions consume it. The
instrument selection rationale and the per-instrument details are
in chapter `06_instruments.md`; the station-side roles are in
chapter `07_station_equipment.md`.

## Instruments

| Item | Qty | Role | Used by | Status |
|---|---|---|---|---|
| Keysight DAQ973A mainframe | 1 | 3-slot measurement mainframe, 6.5-digit (22-bit) DMM, frequency function 3 Hz - 300 kHz | Static Impedance, Power Voltage, slow Clock Hz | **Must** |
| Keysight DAQM908A multiplexer | 2 (slots 1-2) | 40-ch single-ended multiplexer each, `2-wire Ω then DCV` reuse | Static Impedance (80 nets), Power Voltage | **Must** |
| Keysight DAQM907A multifunction | 1 (slot 3) | 16-ch open-drain DIO, 2 x ±12 V AO, 100 kHz totalizer | fixture ops (clamp / lock / E-Stop), ADC Stimulus, CLK1 | **Must** |
| Keysight U2355A USB DAQ | 1 | 16-bit AI, 250 kSa/s aggregate; 2 counters 0.1 Hz - 6 MHz; 24 TTL DIO (out / in) | DAQ AI power-rails capture, Clock Hz > 300 kHz, Control IO DIO Read / Write | **Must** |
| Keysight N5747A system PSU | 1 | 60 V / 12.5 A / 750 W, 4-wire remote sense | Power On / Off DUT | **Must** |

All five are mandatory for the reference plan: the ICT stage
(impedance -> voltage -> clocks -> rails) touches every one of them.

## Peripherals

| Item | Qty | Role | Used by | Status |
|---|---|---|---|---|
| Test AP / Wi-Fi router | 1 | known SSID + credentials for the DUT WLAN | FCT `WIFI` method (`wifi_test`, `iperf3`) | **Must** for products with Wi-Fi, else - |
| Bluetooth reference device | 1 | headset / peer the DUT must discover | FCT `Bluetooth` method (`bt_test`) | **Must** for products with BT, else - |
| USB-to-serial adapter(s) | per DUT | DUT debug console for the operator / scripts | FCT console methods (`SendtoConsole` ...) | **Must** |
| Ethernet router / switch | 1 | DUT LAN + iperf throughput | SSH console, throughput tests | Optional |
| HDMI display | 1 | visual output check (operator confirms) | FCT `MessageYesNo` display checks | Optional |
| Camera module | 1 | CSI-MIPI camera check | FCT visual checks | Optional |
| Microphone / earphone | 1 | audio path check | FCT audio checks | Optional |
| Speaker | 1 | audio output check | FCT audio checks | Optional |
| Media converter (T1/T1S) | 1 | telecom media tests | - | Optional |

The optional rows map to product-specific FCT steps: a plan without
the matching test steps never touches the hardware, so the item can
be left out of that station's BoM.

## Cables and Accessories

| Item | Qty | From -> To | Used by | Status |
|---|---|---|---|---|
| GPIB cable | 1 | HOST PC (GPIB controller) -> DAQ973A `GPIB0::9` | every DAQ973A / DAQM908A / DAQM907A measurement | **Must** (or LAN / USB alternative) |
| USB cable | 1 | HOST PC -> U2355A (`USB0::0x2A8D::0x3018::...`) | power-rails capture, fast clocks | **Must** |
| LAN cable | 1 | HOST PC -> N5747A (`TCPIP0::192.168.1.20::inst0`) | DUT power control | **Must** (or GPIB / USB) |
| USB-GPIB controller | 1 | HOST PC USB -> GPIB bus | the DAQ973A connection | **Must** unless the PC has a PCIe GPIB card or LAN is used |
| Fixture harness (mux) | 1 set | DAQM908A #1 / #2 terminal blocks -> fixture test points TP_P1 - TP_P80, 2-wire pairs | Impedance + Voltage routing | **Must** |
| AI sense harness | 1 | U2355A AI01 - AI12 -> rail sense points at the fixture | power-rails waveform | **Must** |
| DIO / AO wiring | 1 set | DAQM907A DIO01 - DIO16, AO0 / AO1 -> fixture actuators + analog test points | fixture ops, ADC Stimulus | **Must** |
| Control IO DIO wiring | 1 set | U2355A DIO01 - DIO24 -> level shifters -> DUT control-IO nets (non-mux GPIO / EN / CS / RST) | DIO Read / DIO Write ops | **Must** for plans with Control IO rows |
| PSU power + sense wiring | 1 set | N5747A output + 4-wire sense -> fixture power blades (sense AT the load) | DUT power integrity | **Must** |
| Serial console cable(s) | per DUT | HOST PC COM port -> DUT debug UART | FCT console keyword tests | **Must** |

## Test Fixture

- **Fixture probe board** - pogo-pin board, 128 pinhole pins with a
  single-point star ground plane; power net points TP_P1 - TP_P80
  (**Must**).
- **ATE fixture control board** - driven by the DAQM907A Port 1 / 2
  (4 of 16 signals used): clamp `press`, `inpos`, DUT presence,
  E-Stop chain (**Must** for ATE mode; in Manual Fixture mode the
  operator performs every clamp action by hand and no IO control is
  wired).
- **Fixture mechanics** - clamps / press cylinder + E-Stop button
  (**Must** in ATE mode).

## HOST PC Requirements

- **OS** - Windows 11 Pro x64 (the reference configuration of the
  HOST PC block; the GUI also runs on macOS for development).
- **Software** - MTK GUI (mtk-gui) plus the host CLI tools used by
  the FCT RF steps: `wifi_test`, `bt_test`, `iperf3`.
- **Ports** - 1 x USB for the U2355A, 1 x GPIB controller (or LAN /
  USB for the DAQ973A), 1 x LAN for the N5747A / router, one COM
  port per DUT console channel (USB-to-serial).
- **Display** - a screen that fits the GUI layout comfortably
  (the guide layout assumes >= 1400 px width).

## BoM by Test Feature

Which BoM items each feature needs - use it to strip a station down
for a reduced plan:

| Feature | Instruments | Peripherals | Notes |
|---|---|---|---|
| Impedance Shorts | DAQ973A + DAQM908A x2 | fixture harness | stop policy `Stop if any short` |
| Power Voltage | DAQ973A + DAQM908A x2 + N5747A | PSU + sense wiring | needs the DUT powered |
| Clock Hz | DAQ973A (slow) and/or U2355A (fast) | clock taps at the fixture | per-net resource from the channel allocation |
| Power rails (DAQ AI) | U2355A + N5747A | AI sense harness | CSV + AI review |
| FCT console tests | - | USB-to-serial adapter(s) | serial or SSH console channel |
| Flash FAT / OOBE | programmer gateway | flash probe | per-probe integration not yet developed |
| FCT Wi-Fi | - | test AP | `WIFI` method |
| FCT Bluetooth | - | BT reference device | `Bluetooth` method |
| Reports / logs | - | - | HOST PC local files |
