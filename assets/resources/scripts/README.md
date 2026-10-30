# resources/scripts/ - Linux shell scripts

Per-test helper scripts pushed to the DUT and executed over the
console serial channel.

Working examples to copy: `projects/FRDM-IMX93/scripts/`
- `connect_wifi.sh`   (station connect + power-save off, parameterized)
- `load_rf_drivers.sh`(driver load + A2DP sink, merged & idempotent)

Conventions (same as the examples):
- idempotent; parameterized via env vars / args (no hard-coded MAC/IP)
- print SUCCESS/FAIL markers the FCT console step can match:
  `echo "STEPNAME_OK <summary>"` / `echo "STEPNAME_FAIL <reason>"`
- do not write logs into the pushed folder (the DUT is cleaned after
  the tests with a `Console_serial` step, e.g. `rm -rf /tmp/fct_assets`)
