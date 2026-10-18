# Station Equipment

This chapter covers the station equipment AROUND the rack
instruments: the HOST PC, the flash / debug probes (programmers)
and the test peripherals (Wi-Fi, Bluetooth, router, display,
camera, audio). All of them appear on the Equipment page block
diagram (chapter `05_equipment.md`); this chapter explains their
role in the test flow and their current integration status -
features that are planned but not implemented yet are marked
**not yet developed** (placeholder).

## HOST PC

The HOST PC runs the MTK GUI and hosts every station-side
resource.

- **Configuration (Equipment page block)** - Platform
  `Common Test Platform`, Test SW `mtk-gui <version>`, OS
  `Windows 11 Pro x64`, Functions `ICT / FCT / Flash / Reports /
  Cloud`.
- **In the tests** - the FCT stage runs on the HOST PC: the console
  channels (serial / SSH) open from here, and the host CLI tools
  (`wifi_test`, `bt_test`, `iperf3`) execute the RF connectivity
  steps. Reports, CSV logs and the Event Log are written here.
- **Status** - fully integrated (the application itself runs on
  this machine).

## Flash / Debug Probes (Programmer)

The `Flash / Debug Probes` block on the Equipment page lists the
supported programmers:

| Item | Role | Interface |
|---|---|---|
| J-Link | ARM flash / debug | USB |
| PE Micro | NXP flash / debug | USB |
| Lauterbach | TRACE32 debug / trace | USB |
| CMSIS-DAP | CMSIS standard probe | USB HID |
| MCU-LINK | NXP MCU probe | USB HID |
| OpenSDA | NXP OpenSDA | USB |

- **In the tests** - flash operations (`Flash FAT`, `Flash OOBE`)
  route through the instrument gateway; without a programmer
  gateway connected the step reports
  `no programmer gateway connected (Real mode)`.
- **Flashing** - each flash step picks a path via `mode`: `auto`
  drives the probe's CLI tool and judges its output on the
  configured keywords, `manual` opens the third-party GUI and takes
  the operator GO / STOP as the verdict.
- **Status** - the CLI profile of every probe (executable, command
  templates, output patterns, timeout) is edited on its Flash /
  Debug Probes row and saved with the project YAML; the legacy
  J-Link driver path still runs when a probe has no profile.

## Test Peripherals

The `Test Peripherals` block lists the station-side RF / media
resources. Some of them are already used by the FCT stage through
the host CLI; their Equipment-page configuration and health checks
are **not yet developed** (placeholder) unless noted:

| Item | Role | Used by | Status |
|---|---|---|---|
| PC Wi-Fi | RF connectivity | FCT `WIFI` method (`wifi_test`, `iperf3`) | in use via host CLI; equipment config **not yet developed** |
| PC Bluetooth | RF connectivity | FCT `Bluetooth` method (`bt_test`) | in use via host CLI; equipment config **not yet developed** |
| Ethernet Router | LAN / iperf throughput | throughput tests | **not yet developed** |
| Media Converter | T1 / T1S media | - | **not yet developed** |
| Display | DSI-MIPI check | - | **not yet developed** |
| Camera | CSI-MIPI check | - | **not yet developed** |
| Microphone / Earphone | Audio path check | - | **not yet developed** |
| Speaker | Audio output check | - | **not yet developed** |

**Note:** the peripheral rows show `Not connected` in the Equipment
page table; connecting and health-checking them from the GUI is
part of a future iteration.

## Fixture Hardware

The fixture layer (probe board, ATE fixture control board, press
cylinder, in-position / presence / E-Stop cells) is configured and
driven through the DAQM907A DIO lines - its configuration windows,
Manual Fixture mode and the safety chain are described in chapter
`05_equipment.md` (What the Diagram Shows, Permissions and Modes).
