# FCT RF step editors - Equipment sources (M83/C11)

The Wi-Fi / Bluetooth step dialogs show every hardware identity field
**read-only**, resolved from the Equipment page. One mapping table drives
both the dialog and the runtime reference (`ref`) seeded on save.

| Step | Field | Equipment source (first non-empty wins) |
|---|---|---|
| Wi-Fi: Scan | AP SSID | `equipment.peripherals.router.router_ap_ssid` → `equipment.peripherals.router.hotspot_ssid` → `equipment.peripherals.wifi.ap_ssid` |
| Wi-Fi: Scan | DUT SSID | `equipment.dut.wifi.ssid` |
| Wi-Fi: Ping | Target IP | `equipment.peripherals.router.dut_ip` |
| Wi-Fi: iPerf | Host server IP | `equipment.peripherals.router.wifi_host_ip` → `equipment.peripherals.wifi.host_ip` |
| Bluetooth: RSSI | DUT BT name | `equipment.dut.bluetooth.name` |
| Bluetooth: RSSI | BD address | `equipment.dut.bluetooth.bd_addr` |
| Bluetooth: Pair | DUT BT name | `equipment.dut.bluetooth.name` |
| Bluetooth: Pair | Pair script | runs through the console serial channel (`ser1` by default) |

The M65 "Wired & Wireless Network" fields are the editable source; the
legacy `peripherals.wifi.*` keys remain as fallbacks for old projects.
A missing value renders as `—` and is listed in the dialog's
"Missing in Equipment" warning banner (warning only, OK is never blocked).

Editable fields in these dialogs are test-only: RSSI limits, counts,
duration, timeout, scan-via, tool, L2CAP ping count (minimum 1) and the
tone wav / segment slider.
