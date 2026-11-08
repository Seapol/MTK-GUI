# FRDM-IMX93 — reference assets

This folder is the worked example that ships with the FRDM-IMX93 project. It
exists so you can see a complete, running asset set before writing your own.
Your project gets its own `assets_<PROJECT>/` folder, created from the
application skeleton — not a copy of this one.

## What is here

| File | What it shows |
|---|---|
| `precheck/01_system_check.sh` | a pre-flight check that prints `_OK` / `_FAIL` markers |
| `drivers/load_drivers.sh` | Wi-Fi + BT driver bring-up on a bare Linux DUT |
| `resources/scripts/connect_wifi.sh` | joining the station AP, two profiles: `router` and `hotspot` |
| `resources/scripts/bt_conn.sh` | BlueZ pairing helper |
| `resources/config/wpa_supplicant.conf.template` | a config file handed to the DUT, not edited in place |
| `resources/audio/` | audio used by tone / playback steps |
| `templates/` | app-owned sequence templates — never edit, they are replaced with the application |

## What is deliberately blank

The four `AP_PROFILE_*` values in `connect_wifi.sh` are **empty on purpose**.
An access point name and its password belong to one site; committing them here
would hand that site's credentials to everyone who receives the project.

Fill them for your own station, by hand, in any text editor - copy the four
values from **Equipment → Peripherals** (`Wi-Fi router` / `Host PC hotspot`).
There is no in-app editor or sync panel: assets are project data and the
application never writes them. The script reports
`WIFI_CONNECT_FAIL (profile '<name>' is not configured yet)` and stops when a
value is missing, so a half-filled file can never join the wrong network.

The same rule applies to your own project: credentials live in the project
package, never in a shared source tree.

## How to reuse it

- Copy a script and adapt it — do not edit this folder; it is the reference.
- Keep the variable contract of `connect_wifi.sh` intact (`AP_PROFILE_*`,
  one quoted value per line, on its own line). The GUI reads exactly those
  lines to cross-check the Equipment page and warns when they disagree.
- Keep the marker conventions: `echo "STEPNAME_OK <summary>"` and
  `echo "STEPNAME_FAIL <reason>"`. The rest of the rules are listed in the
  skeleton `assets/README.md`.
