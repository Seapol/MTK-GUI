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
| Ethernet Router | LAN / iperf throughput | throughput tests | configured in the `WiFi router` group dialog (Direct / LAN via router / Host hotspot); the throughput run is the FCT `Wifi_Iperf` step |
| Media Converter | T1 / T1S media | - | **not yet developed** |
| Display | DSI-MIPI check | - | **not yet developed** |
| Camera | CSI-MIPI check | - | **not yet developed** |
| Microphone / Earphone | Audio path check | - | **not yet developed** |
| Speaker | Audio output check | - | **not yet developed** |

**Note:** the peripheral rows show `Not connected` in the Equipment
page table; connecting and health-checking them from the GUI is
part of a future iteration.

**Host radios have no entry in this table.** The FCT `WIFI` and `Bluetooth`
steps drive the host Wi-Fi and Bluetooth adapters through the command line
(`wifi_test`, `iperf3`, `bt_test`); their station parameters are edited under
`Test Peripherals` -> `wifi` / `bluetooth` / `router` group dialogs on the
Equipment page.

## Wi-Fi Network Modes

The DUT reaches the network through one of two wireless modes, and the
mode is a **station-level** choice made on the Equipment page before a
run. The DUT side is an ordinary `Console_serial` row that runs a DUT
script; the row carries **no credentials**, only the profile name.

| Mode (Equipment page) | Who is the access point | Host PC behaves as |
|---|---|---|
| `Wi-Fi router` | an external Wi-Fi router | joins the same router AP |
| `Host PC hotspot (no router)` | the Windows host PC itself (`netsh` Hosted Network) | runs the AP |

Two wired modes exist as well (`Direct ... (no router)` and
`LAN via router`); they carry no Wi-Fi credentials and are covered by
the block above them.

### Setting up the station side

1. Open `Equipment` and click the `Wired & Wireless Network` block
   (chapter `05_equipment.md`).
2. Select the wireless mode. The two wireless modes are mutually
   exclusive, and the window shows only the fields that belong to the
   selected one.
3. `Wi-Fi router` mode: fill `Router AP SSID` and `Router AP password`.
   The host PC joins that AP and keeps its own link while the DUT joins
   the same one.
4. `Host PC hotspot (no router)` mode: fill `Host PC AP SSID` and
   `Host PC AP password`. The host PC starts the AP with exactly these
   two values. The field accepts an empty password ("open hotspot"), but
   the DUT script requires a WPA2 password - leave it filled.
5. Save the page. These values are station configuration, not per-test
   data.

### Setting up the DUT side

The DUT script `connect_wifi.sh` (pushed onto the DUT by an earlier
`Serial Push` row) keeps **both profiles hard-coded** and selects one by
its first argument:

| Row command | Profile |
|---|---|
`bash /root/fct_assets/connect_wifi.sh router` | external `Wi-Fi router` |
| `bash /root/fct_assets/connect_wifi.sh hotspot` | `Host PC hotspot (no router)` |

Credentials never appear on the command line. The serial console echoes
every command, so a credential typed into the row would also land in the
Console Log and in the DUT PDF report. The argument carries the mode
only.

The SSID / password inside the script and the two fields of the matching
Equipment mode must describe the **same** access point. Two checks run at
build time, both as **warnings** - they never block a build and never change
the sequence, because the script is what the DUT actually joins at run time:

| Check | Warning when |
|---|---|
| profile argument | the `connect_wifi.sh` row carries no `router` / `hotspot` argument (every station would fail at this row) |
| SSID agreement | the script's SSID for that profile differs from the Equipment `Wi-Fi router` / `Host PC hotspot (no router)` AP SSID |

The second warning names both SSIDs and the field to edit, so one of the two
can be corrected. The GUI reads the four declaration lines at the top of the
script (`AP_PROFILE_<PROFILE>_SSID` / `..._PASSWORD`), not the shell bodies;
the local copy it reads is the one the sequence's `Serial Push` row pushes.
Without such a push row there is nothing to compare, and the check stays
silent.

Being a warning, not an error, is deliberate: a mismatch is an operator
mistake that costs one failed row, not a hazardous action, and the run report
already shows `ssid=` on the result line.

### Writing the script by hand

The script and the Equipment page carry the same four values. The application
does **not** copy them for you: `resources/scripts/connect_wifi.sh` is a
project asset, so whoever prepares `assets_<Project>` fills the four lines once,
reading the values from **Equipment → Peripherals**:

| Script line | Equipment field |
|---|---|
| `AP_PROFILE_ROUTER_SSID` | `Wi-Fi router` → Router AP SSID |
| `AP_PROFILE_ROUTER_PASSWORD` | `Wi-Fi router` → Router AP password |
| `AP_PROFILE_HOTSPOT_SSID` | `Host PC hotspot (no router)` → Hotspot SSID |
| `AP_PROFILE_HOTSPOT_PASSWORD` | `Host PC hotspot (no router)` → Hotspot password |

Open the file in any text editor, fill the four quoted values, and push it with
the project's `Serial Push` / SFTP row. Nothing else in the file changes: the
comments and the shell body stay as they are. The application keeps no backup,
so put the project assets under your own version control.

A value left empty stops the run before the DUT is touched, with
`WIFI_CONNECT_FAIL (profile '<profile>' is not configured yet)`. That is a
pre-flight requirement, not a test result: the row only reports what the DUT
answered.

### Reading the result

| Output line | Meaning |
|---|---|
| `WIFI_CONNECTED_OK <ip>/<prefix> profile=<profile> ssid=<ssid>` | the DUT obtained a 192.x address on that profile's AP |
| `WIFI_CONNECT_FAIL (unknown profile '<arg>'; expected router or hotspot)` | the row has no profile argument, or a wrong one |
| `WIFI_CONNECT_FAIL (profile '<profile>' is not configured yet)` | that profile has no credentials in the script |
| `WIFI_CONNECT_FAIL (profile=<profile> ssid=<ssid>: no 192.x address from DHCP)` | the AP was unreachable or DHCP failed |

The result line names the profile and the SSID, so the run report always
shows which access point the unit was tested against - and never the
password.

Switching a station between the two wireless modes means changing one
word in that row and the mode on the Equipment page. The GUI never
rewrites an authored step.

## Fixture Hardware

The fixture layer (probe board, ATE fixture control board, press
cylinder, in-position / presence / E-Stop cells) is configured and
driven through the DAQM907A DIO lines - its configuration windows,
Manual Fixture mode and the safety chain are described in chapter
`05_equipment.md` (What the Diagram Shows, Permissions and Modes).
