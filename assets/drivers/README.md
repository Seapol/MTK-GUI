# drivers/ - RF / BT driver load & setup

Scripts that (re)load the Wi-Fi / Bluetooth kernel modules and prepare
the radio stacks.  The FCT console rows probe first and only run the
load path when the driver is missing ("probe first, load on demand").
The retired `Wi-Fi: Connect DUT to AP` operation is replaced by a
`Console_serial` row that runs your own connect script.

Working example to copy: `projects/FRDM-IMX93/assets_FRDM-IMX93/drivers/load_drivers.sh`
(NXP IW612 combo: brcmfmac/brcmutil + btusb/hci_uart + A2DP sink via
pipewire).  Adapt module names / interface names to your project.

Marker contract:
- success: `DRIVERS_OK <summary>`
- failure: `DRIVERS_FAIL <reason>`
