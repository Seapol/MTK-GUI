# drivers/ - RF / BT driver load & setup

Scripts that (re)load the Wi-Fi / Bluetooth kernel modules and prepare
the radio stacks.  The FCT standard step `Bluetooth: Prepare DUT BT`
and `Wi-Fi: Connect DUT to AP` probe first and only run the load path
when the driver is missing ("probe first, load on demand").

Working example to copy: `projects/FRDM-IMX93/scripts/load_rf_drivers.sh`
(NXP IW612 combo: brcmfmac/brcmutil + btusb/hci_uart + A2DP sink via
pipewire).  Adapt module names / interface names to your project.

Marker contract:
- success: `DRIVERS_OK <summary>`
- failure: `DRIVERS_FAIL <reason>`
