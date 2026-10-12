# DUT Script Assets — FRDM-IMX93 (Linux)

These are the **generic** Linux-side scripts that mtk-gui provisions to
every FRDM-IMX93 DUT over SFTP before the FCT run. They are maintained
here on the Host PC (single source of truth) and copied to the DUT on
**each unit**, so a board whose `/root` was wiped by a reboot or a fresh
image is re-provisioned automatically.

## Layout convention

- Demo / this folder:
  `yaml_plan/examples/imx93frdm/dut_scripts/linux/` (shipped inside the
  `examples` package data).
- Per-product convention:
  `config/<product>/dut_scripts/linux/`.

The whole `dut_scripts` tree is mirrored to the DUT target directory
(`console.scripts_remote_dir`, default `/root`). Test reports are **not**
part of these assets.

## Scripts

| Script | Purpose | Success marker |
|---|---|---|
| `load_rf_drivers.sh` | Load the NXP/u-blox Wi-Fi (`moal`) + BT (`btnxpuart`) drivers and bring interfaces up | `RF drivers loaded OK` |
| `connect_wifi.sh` | Put Wi-Fi in station mode and connect to the factory router AP (Host on the same LAN) | `WIFI_CONNECTED_OK <ip/prefix>` / `WIFI_CONNECT_FAIL` |
| `start_bt_audio.sh` | Start the A2DP sink (pipewire/wireplumber + NoInputNoOutput agent), make the DUT discoverable and trust the Host | `BT_AUDIO_READY` |
| `FCT_SETUP.md` | Board FCT setup checklist | — |

## Runtime parameters (no per-board hard-coding)

Scripts contain no fixed MAC/BD/IP. Environment-specific values are
injected via environment variables (or positional args) at run time:

| Variable | Args | Used by | Meaning |
|---|---|---|---|
| `WIFI_SSID` | `connect_wifi.sh $1` | connect | Factory router AP SSID |
| `WIFI_PASSWORD` | `connect_wifi.sh $2` | connect | AP passphrase (stays on DUT, never in the mtk-gui YAML) |
| `WIFI_IF` | — | load / connect | Wi-Fi interface (default `mlan0`) |
| `HOST_BT_MAC` | `start_bt_audio.sh $1` | bt audio | Host PC BT address to trust |
| `BT_IF` | — | load / bt audio | BT interface (default `hci0`) |

## BSP prerequisites (Linux BSP team's responsibility)

mtk-gui only sends these editable commands and judges their markers; it
does not implement drivers. The BSP must provide:

- the `moal` / `btnxpuart` kernel modules and the NXP Wi-Fi parameter
  file (`/lib/firmware/nxp/wifi_mod_para.conf`);
- `wpa_supplicant`, `udhcpc`, `bluez` (`bluetoothctl`, `hciconfig`);
- for the A2DP test: `pipewire` + `wireplumber` + `libspa-bluez5` (SBC);
- a running SSH server for SFTP (start it, or mtk-gui sends
  `mkdir -p /run/sshd && /usr/sbin/sshd` over the serial console).

Drivers may either auto-load at boot or be loaded by `load_rf_drivers.sh`.
