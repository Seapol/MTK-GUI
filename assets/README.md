# Assets — what you have to prepare

This folder is a **skeleton**, not a working set. Everything the DUT needs at
run time — driver load scripts, DUT-side shell scripts, audio files, static
configs — is written and debugged by you, and it lives **inside the project
folder**, never inside the application.

The application ships this skeleton and the sequence templates only. Nothing
here is DUT-specific until you fill it in.

## Where the folder belongs

```text
projects/
└── <PROJECT>/                  one folder per production project
    ├── <PROJECT>_*.yaml        the project plan
    └── assets_<PROJECT>/       THIS skeleton, filled in by you
        ├── precheck/           pre-flight checks
        ├── drivers/            RF / BT driver load
        ├── resources/
        │   ├── scripts/        DUT-side shell scripts
        │   ├── audio/          audio files
        │   ├── config/         static configs
        │   └── patches/        kernel / BSP patches
        └── templates/          app-owned — do not edit
```

Create the folder yourself: copy this whole skeleton to
`projects/<PROJECT>/assets_<PROJECT>/`, keeping the directory names, then fill
in your own files. The application does not create, edit or sync assets - it
only reads them, and it reads them from the project folder. Do not rename the
copy to plain `assets/`: that is the older convention, still readable, but the
GUI then reports `(built-in fallback)` instead of `(assets ready)`.

## What goes in each folder

| Folder | You put here | Reaches the DUT by |
|---|---|---|
| `precheck/` | system / interface health checks, one script per concern | `Serial: Push file to DUT`, then run it |
| `drivers/` | Wi-Fi / BT driver load and interface-up scripts | your FCT step; the Wi-Fi page also drives the interface probe |
| `resources/scripts/` | DUT-side shell scripts (`connect_wifi.sh`, `bt_conn.sh`, ...) | `Serial: Push file to DUT` or `SFTP_put` |
| `resources/audio/` | wav files for tone / playback tests | push, then play from the sequence |
| `resources/config/` | `wpa_supplicant.conf`, any static config | push before the step that uses it |
| `resources/patches/` | kernel / BSP patches | push before the step that applies them |
| `templates/` | **app-owned** sequence templates | replaced with the application — never edit |

`resources/scripts/connect_wifi.sh` is a fixed name: project validation reads
it to check that the Wi-Fi join step names a profile.

## Rules that decide whether a test can judge PASS

1. **Only the console serial port is guaranteed.** A freshly flashed DUT has a
   plain Linux BSP or bare-metal firmware and no pre-configuration. Every
   asset you write must assume that.
2. **Steps address files as `assets/<rest>`.** When a template or plan is
   loaded, the GUI rewrites that prefix to the project's `assets_dir`, so keep
   the sub-paths (`resources/scripts/...`) stable. Move a file and you must
   fix the step's Local field.
3. **Print marker lines.** The FCT message test judges text, not exit codes:
   `echo "STEPNAME_OK <summary>"` on success,
   `echo "STEPNAME_FAIL <reason>"` on failure.
4. **Be idempotent and parameterised.** No hard-coded MAC, IP or serial; take
   them from arguments or environment. The same folder must work on every DUT
   of the project.
5. **Push under one directory.** Deploy targets go under `/root/fct_assets`,
   so the whole set can be removed with a single `rm -rf` if you decide to
   clean up at end of test.
6. **Keep it small.** Serial push is base64 over a 115200 console and is slow;
   prefer `SFTP_put` whenever the DUT has a network. Keep single files in the
   low hundreds of KB.

## Do not put here

- Windows binaries, installers, vendor setup packages.
- Absolute paths from your own PC — the station resolves inside the assets
  tree, never on your drive.
- Per-DUT values (MAC, serial number, batch) — those belong to the run, not to
  the assets.
- Credentials shared beyond this project. A project's SSID / password belongs
  in that project's own assets folder, because that folder is what gets
  published for that project.

## Sign-off before you publish the project

- [ ] `assets_<PROJECT>/` exists with the exact name and the GUI shows
      `(assets ready)` for this project.
- [ ] the `precheck` script runs on a bare DUT and prints its markers.
- [ ] the driver script brings the interface up; `iw dev <iface> info` answers.
- [ ] every push step's Local path resolves inside the assets tree.
- [ ] every script prints `_OK` / `_FAIL` markers.
- [ ] audio files play on the DUT and stay within the size budget.
- [ ] `templates/` is untouched.
