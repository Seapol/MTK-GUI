# MTK GUI — Station Package

This package is the MTK GUI runtime for a factory station. It contains the
application and nothing else: no source code, no build tools, no Python, no
sample projects.

## What you received

| Package | Item | Contents | Where it goes |
|---|---|---|---|
| **MTK GUI App** `<tag>` | managed as its own versioned item | the application, its help and its sequence templates | `D:\MTK_Station\app\` |
| **`<PROJECT>`** `<rev>` | one item per product project | one project folder, including `assets_<PROJECT>\` | `D:\MTK_Station\work\projects\` |

The project item records which app tag it was validated against. Use exactly
that tag on the station — do not mix a newer app with an older project.

Without a project package the application opens but has no plan to run.

## Layout

```text
D:\MTK_Station\
├── app\                 the application - replaced wholesale at each app release
├── work\                all station state - never replaced
├── MTK_GUI_Start.bat    the only supported launcher
└── README.md            this file
```

`app\` is read-only in practice: do not edit anything under it and do not add
your own files there. Everything you configure or produce lives in `work\`.

## 1. Install

1. Extract the MTK GUI App package so that `app\MTK_GUI.exe` and
   `MTK_GUI_Start.bat` sit directly under `D:\MTK_Station\`.
2. Do not put the folder on a network drive or inside a cloud-synced folder.
3. If Windows shows a SmartScreen warning, allow the file — the binary is
   not signed.

## 2. First start

Double-click **`MTK_GUI_Start.bat`**, not the exe. The launcher fixes the
working directory and tells the application where its writable folders are:

| Variable | Value |
|---|---|
| `MTKGUI_TENANT_BASE` | `work\projects` |
| `MTKGUI_REPORT_HOME` | `work\reports` |
| `MTKGUI_OUTBOX_DIR` | `work\outbox` |
| `MTKGUI_ACCOUNTS` | `work\audit\accounts.json` |
| `MTKGUI_AUDIT_LOG` | `work\audit\audit.jsonl` |

`work\` is created on the first start. Log in as **Operator** in **Real**
mode; production stations never run Virtual mode.

**Set the computer name before the first start.** The computer name is the
station identity: it is written as **Station ID** into every Event Report row,
every audit entry and every MES CSV. Renaming the machine later leaves the
history inconsistent, so pick the final name first and keep one Operator
account per station rather than per person.

If you want a desktop shortcut, point it at `MTK_GUI_Start.bat` and set the
shortcut's **Start in** to `D:\MTK_Station`.

## 3. Instruments

1. Install the instrument vendor's IO libraries **before** plugging anything
   in, then confirm each instrument answers `*IDN?` in the vendor's
   connection utility.
2. In MTK GUI, open the **Equipment** page and fill in the resource string
   exactly as the connection utility reports it
   (`GPIB0::9::INSTR`, `TCPIP0::<ip>::inst0`).
3. Connect every instrument from the Equipment page before the first run.
   Without a working gateway each instrument-dependent row reports **Error**
   by design — a blank PASS is not possible.

## 4. Add a project

The application ships with **no** sample project — every project you run
comes from its own project package.

1. Extract the project package into `work\projects\` — one folder per project,
   folder name exactly as published.
2. Confirm the folder carries `assets_<PROJECT>\` with the scripts, drivers
   and audio files for this DUT. A project shipped without it runs on the
   built-in skeleton, which is not production-ready; the project row then
   shows `(built-in fallback)` instead of `(assets ready)`.
3. Do not edit files under `app\_internal\`, and do not re-author the plan on
   a production station — plan changes go back to the project item and are
   republished.

## 5. Verify a station

Read the version first, then run one DUT. All four must hold:

- `app\VERSION.txt` and **Help → About** show the same tag and commit, and
  that tag is the one written in your project item.
- **Help → User Guide** opens and lists the chapters (the guide ships inside
  `app\`; if it does not open, the package was zipped incompletely).
- `work\reports\<PROJECT>\DUT Report\` contains one new folder for that DUT,
  holding the DAQ CSV, the certificate PDF and the MES CSV. DUT reports are
  filed per project so a finished project can be archived as one folder.
- `work\reports\Event Report\` — station-level, **not** per project (a station
  is shared by several projects) — has today's entries. Each line is just
  `timestamp + message`; when a plan is loaded or the project is switched, a
  single marker line `>> project 96317_IMXRT700` is written, so a session that
  spans two projects can still be told apart. The station is identified by the
  machine this log sits on — the **Station ID** and **Operator** columns live
  in the DUT report, not here. This log stays on the station: it is the
  traceback record when something goes wrong, and it is never packed up with a
  project.

A run that is stopped or aborted produces **no report** — it is void by
design. Only a run that reaches the end generates a DUT report. Stopping a run
still executes the cleanup steps, so the DUT is left powered down and
disconnected.

If a report lands under `app\` instead, the launcher was bypassed — close the
GUI and start again through `MTK_GUI_Start.bat`.

## 6. Upgrade, rollback, backup

| Task | Do |
|---|---|
| Upgrade the app | close the GUI (`File → Exit`), replace only `app\`, leave `work\` untouched, start again |
| Upgrade one project | close the GUI, replace that single folder under `work\projects\`, start again |
| Rollback | rename the previous `app\` to `app_<oldtag>\` before replacing; rename it back to `app\` to roll back |
| Archive a finished project | take `work\projects\<PROJECT>\` together with `work\reports\<PROJECT>\`; the Event Report stays on the station |
| Backup the station | `work\` in full — accounts, permissions, projects, DUT reports, event log |

Replace nothing while the GUI is running, and never delete `work\`.

## 7. Do not

- Do not launch `app\MTK_GUI.exe` directly — accounts, reports and projects
  then land under `app\` and disappear at the next app release.
- Do not edit anything under `app\`; the next release replaces it.
- Do not grant Operator accounts Supervisor rights just to make a plan
  editable — plan edits are republished from the project item instead.
- Do not run Virtual mode on a production station.

## 8. Network profiles (Wi-Fi router / direct)

The DUT Wi-Fi script carries **two** profiles and picks one by its first
argument: `router` (used by the `LAN via router` / `Wi-Fi router` mode) and
`hotspot` (used by `Host PC hotspot (no router)`). Both profiles live in one file:

```text
work\projects\<PROJECT>\assets_<PROJECT>\resources\scripts\connect_wifi.sh
```

Fill exactly these four lines (lines 41-44 of the source tree copy) with the
access point the station actually uses:

| Line | What it is for |
|---|---|
| `AP_PROFILE_ROUTER_SSID` | SSID of the external router AP (`LAN via router` / `Wi-Fi router`) |
| `AP_PROFILE_ROUTER_PASSWORD` | its WPA2 password |
| `AP_PROFILE_HOTSPOT_SSID` | SSID the Windows host broadcasts (`Host PC hotspot`) |
| `AP_PROFILE_HOTSPOT_PASSWORD` | its WPA2 password |

These are the **only four values an installer must type**. An empty value
makes the Wi-Fi step fail loudly with
`WIFI_CONNECT_FAIL (profile '<name>' is not configured yet)`, so a half-filled
file can never join the wrong network. The same four values are entered on the
Equipment page (`Wired & Wireless Network` block) - keep the two in agreement.

## 9. SharePoint upload

The site configuration for each project lives in:

```text
work\sharepoint\<PROJECT>\sharepoint_upload.json
```

Next to it the application keeps `state.json` (the Shopfloor light and the
pending list) and `upload_ledger.json` (the deduplication ledger). The
configuration is per project - two projects on one station never share a site.

The **Shopfloor light** in the status bar reports the last upload: grey = not
configured, green = uploaded and nothing pending, amber = uploading or files
waiting to retry, red = failed (the files stay in the outbox). Hover it for the
reason.

Uploads run **by themselves**: at the end of every run, and once at startup for
whatever the previous session left pending. The `Report → SharePoint Upload…`
dialog is currently disabled for the operator (2026-10-27); its upload path and
the on-open retry stay in place for when a simpler sign-in flow is approved.
Leaving the GUI with `File → Exit` waits for an upload in flight - never kill
the process instead.

The browser sign-in (embedded sign-in window) is done **once per app
installation** and kept with the application; no password is stored. After an
app replacement, sign in again if the window asks.

## Support

When a station misbehaves, keep `work\` and take: the station's computer name,
the tag from `app\VERSION.txt`, the last entries of `work\audit\audit.jsonl`,
and the `work\reports\Event Report\` folder for the failing DUT.
