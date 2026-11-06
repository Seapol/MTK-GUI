# precheck/ - system pre-flight checks

Run these scripts on the DUT (serial) BEFORE the production tests to
confirm the BSP state: kernel, board model, storage, RF drivers.

Working example to copy: `projects/FRDM-IMX93/assets_FRDM-IMX93/precheck/01_system_check.sh`
(NXP i.MX93).  Adapt board model string, expected interface names and
thresholds to your project.

Marker contract (FCT message test):
- success: `PRECHECK_OK <summary>`
- failure: `PRECHECK_FAIL <reason>`
