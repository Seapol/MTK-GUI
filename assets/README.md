# MTK-GUI Project Assets Template

This folder lives at the repo default root (`assets/`) and ships with
the packaged app inside `_internal/assets`.  Copy it into your local
project folder, next to the project YAML, and adapt it to your DUT:

```text
projects/
  <YourProduct>/
    <YourProduct>_..._rev_1.0.0_Draft.yaml   <- your project YAML (existing)
    assets/                                   <- THIS template, copied here
      precheck/                               system pre-flight checks
      drivers/                                RF / BT driver load & setup
      resources/
        scripts/                              Linux shell scripts (bt_conn.sh, ...)
        audio/                                audio files (BT Tone / music)
        config/                               static configs (wpa_supplicant, ...)
        patches/                              kernel / BSP patches
```

## Usage rules (owner-confirmed)

- Every production DUT runs a plain Linux BSP / Bare-metal firmware
  with NO pre-configuration.  All real preparation happens inside FCT
  Sequence steps at run time; only the console serial port is
  guaranteed available.
- Files in `assets/` are pushed to the DUT over SERIAL or SFTP by
  standard FCT steps (`Serial: Push file to DUT`, `SFTP_put`, ...),
  and test logs are pulled back with `Serial: Pull file from DUT` /
  `SFTP_get`.
- **Deploy target convention**: pushed files go under the DUT
  `/root` (e.g. `/root/fct_assets`), so the whole set CAN be cleaned
  in one shot.
- **End-of-test cleanup (optional, user-decided)**: after the last
  test the operator may pull the logs, then delete EVERY file the
  tests left behind, then power the DUT off — all via ordinary steps
  (`Serial: Pull file from DUT` -> `Console_serial` `rm -rf
  /root/fct_assets` -> `Power Off DUT`).  Keeping the files is
  equally valid: e.g. the Linux image lives on a test-only SD card
  that does NOT ship with the product, so the operator reuses it and
  just unplugs the card — no per-run transfer cost.  Nothing is
  auto-deleted and nothing is forced; every cleanup step is user
  orchestrated.
- Keep scripts idempotent and parameterized (env vars / args, NO
  hard-coded board MACs or IPs): the same asset folder must work on
  every DUT of the project.
- Print SUCCESS/FAIL marker lines so the FCT message test can judge
  them (FCT passes when the SUCCESS marker appears, fails when the
  FAIL marker appears):
  `echo "STEPNAME_OK <summary>"` / `echo "STEPNAME_FAIL <reason>"`

## Reference example (real, working)

`projects/FRDM-IMX93/scripts/` already contains production-quality
examples you can copy from:

- `preflight.sh`            -> model for `precheck/`
- `load_rf_drivers.sh`      -> model for `drivers/` (Wi-Fi + BT + A2DP)
- `connect_wifi.sh`         -> model for `resources/scripts/`

Copy the template to a new project (dev repo):

```bash
cp -R assets projects/<YourProduct>/assets
# then edit every file under your project assets
```

On the deployment machine the template is at `_internal/assets`
(next to the exe):

```bash
cp -R _internal/assets projects/<YourProduct>/assets
```
