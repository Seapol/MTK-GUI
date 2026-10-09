# Linux DUT OS Setup Guide for FCT Testing

This guide describes the Linux-side operations required on a Full Stack Linux DUT (e.g., NXP FRDM-IMX93) before FCT testing. It is intended for BSP/factory engineers.

---

## 1. Post-Boot Check List

After the DUT boots, verify:

```bash
# System info
uname -a
cat /etc/os-release

# Network interfaces exist
ip link show

# SSH server running
systemctl status sshd
```

---

## 2. Wi-Fi Driver Loading

### 2.1 Check if Wi-Fi driver is loaded

```bash
# List Wi-Fi interfaces
ip link show wlan0

# Check kernel module
lsmod | grep -i wifi
lsmod | grep -i nl80211
```

### 2.2 If driver not loaded (BSP provides script)

If BSP team provides a driver load script:

```bash
# Option A: Auto-load at boot (recommended)
# Add to /etc/modules-load.d/wifi.conf:
#   <wifi_module_name>
# Then run:
systemctl restart systemd-modules-load

# Option B: Manual load via script
sh /opt/load_wifi_drivers.sh
```

### 2.3 Verify Wi-Fi interface

```bash
# Should show wlan0 with MAC address
ip link show wlan0

# Scan available networks (station mode test)
iw dev wlan0 scan | grep SSID
```

---

## 3. Bluetooth Driver Loading

### 3.1 Check if Bluetooth driver is loaded

```bash
# List Bluetooth controllers
hciconfig

# Check kernel module
lsmod | grep -i bluetooth
lsmod | grep -i btusb
```

### 3.2 If driver not loaded

```bash
# Load Bluetooth module
modprobe btusb
modprobe bluetooth

# Or via BSP script
sh /opt/load_bt_drivers.sh

# Verify
hciconfig hci0
# Should show: UP RUNNING
```

### 3.3 Enable Bluetooth device

```bash
hciconfig hci0 up
hciconfig hci0
# Expected output:
# hci0: Type: Primary  Bus: USB
#   BD Address: XX:XX:XX:XX:XX:XX  ACL MTU: 0:0  SCO MTU: 0:0
#   UP RUNNING
```

---

## 4. Network Configuration

### 4.1 Set up ethernet (for SSH/SCP)

```bash
# Check ethernet interface
ip link show eth0

# Set static IP (or DHCP)
# DHCP:
dhclient eth0

# Or static:
ip addr add 192.168.1.100/24 dev eth0
ip link set eth0 up
```

### 4.2 Enable SSH server

```bash
# Install openssh-server if needed
apt install openssh-server

# Enable and start
systemctl enable sshd
systemctl start sshd

# Verify
systemctl status sshd
ss -tlnp | grep :22
```

### 4.3 Note DUT IP address

```bash
ip addr show eth0 | grep inet
# Record this IP for Host PC SSH/SCP
```

---

## 5. Wi-Fi AP Mode (for full_stack testing)

If DUT acts as Wi-Fi AP (Host PC connects to DUT hotspot):

### 5.1 Install hostapd and dnsmasq

```bash
apt install hostapd dnsmasq
```

### 5.2 Configure hostapd

Create `/etc/hostapd.conf`:
```ini
interface=wlan0
driver=nl80211
ssid=DUT-AP-XXXX
hw_mode=g
channel=6
wpa=2
wpa_passphrase=your_password
wpa_key_mgmt=WPA-PSK
rsn_pairwise=CCMP
```

### 5.3 Configure Dnsmasq (DHCP for Wi-Fi clients)

Create `/etc/dnsmasq.conf`:
```ini
interface=wlan0
dhcp-range=192.168.4.2,192.168.4.20,255.255.255.0,24h
```

### 5.4 Set static IP on wlan0

```bash
ip addr add 192.168.4.1/24 dev wlan0
ip link set wlan0 up
```

### 5.5 Start AP

```bash
hostapd /etc/hostapd.conf &
dnsmasq &
```

### 5.6 Verify AP is up

```bash
# On Host PC, should see SSID "DUT-AP-XXXX"
# Ping DUT gateway 192.168.4.1
```

---

## 6. Bluetooth A2DP Sink Setup

For audio playback test (Host PC sends audio to DUT headphone jack):

### 6.1 Install BlueZ and audio packages

```bash
apt install bluez bluez-tools pulseaudio pulseaudio-module-bluetooth
```

### 6.2 Start Bluetooth service

```bash
systemctl start bluetooth
systemctl status bluetooth
```

### 6.3 Verify A2DP sink profile

```bash
# List available Bluetooth controllers
hciconfig

# Check PulseAudio Bluetooth modules
pactl list modules | grep bluetooth

# Should see: module-bluetooth-policy, module-bluetooth-discover
```

### 6.4 Pairing (done from Host PC side)

The Host PC (Mac/Windows) initiates pairing. On DUT:

```bash
# Make Bluetooth discoverable
bluetoothctl
[bluetoothctl]# power on
[bluetoothctl]# discoverable on
[bluetoothctl]# pairable on
[bluetoothctl]# agent on
[bluetoothctl]# default-agent
```

### 6.5 Verify audio sink

After Host PC connects:
```bash
# List PulseAudio sinks
pactl list sinks

# Should see a Bluetooth sink corresponding to Host PC
```

---

## 7. OOBE Firmware Flash (uuu.exe)

OOBE image is flashed from Host PC using NXP uuu tool.

### 7.1 Prepare DUT for USB download mode

1. Power off DUT
2. Set bootstrap pins to USB download mode (per hardware manual)
3. Power on DUT

### 7.2 On Host PC (not DUT)

```bash
# Flash OOBE image
uuu.exe -b oobe_image.sd

# Wait for "Success" output
# Then power cycle DUT
```

### 7.3 Verify boot into OOBE image

After flash, DUT should boot into OOBE image. Verify via serial console:
```bash
# Serial console output should show OOBE boot log
```

---

## 8. Pre-Test Summary Script

BSP engineer can run this script on DUT before FCT:

```bash
#!/bin/bash
# /opt/fct_precheck.sh

echo "=== FCT Pre-Check ==="
echo ""

echo "[1] System:"
uname -a
echo ""

echo "[2] Network interfaces:"
ip link show
echo ""

echo "[3] Wi-Fi interface:"
ip link show wlan0 || echo "wlan0 NOT FOUND"
echo ""

echo "[4] Bluetooth controller:"
hciconfig hci0 || echo "hci0 NOT FOUND"
echo ""

echo "[5] SSH server:"
systemctl is-active sshd || echo "sshd NOT RUNNING"
echo ""

echo "[6] IP address:"
ip addr show eth0 | grep "inet " || echo "No eth0 IP"
echo ""

echo "=== Pre-Check Complete ==="
```

Save as `/opt/fct_precheck.sh`, make executable:
```bash
chmod +x /opt/fct_precheck.sh
```

---

## 9. Notes for BSP Team

- **Driver loading**: If Wi-Fi/Bluetooth drivers are not auto-loaded at boot, provide `/opt/load_wifi_drivers.sh` and `/opt/load_bt_drivers.sh`. mtk-gui can call these via SSH.
- **Auto-load recommended**: Best practice is adding modules to `/etc/modules-load.d/` so no manual step needed.
- **SSH must be enabled**: Required for SCP file transfer and remote command execution.
- **A2DP sink**: Required only if Bluetooth audio playback test is needed.
- **uuu.exe runs on Host PC**, not on DUT. DUT only needs to be in USB download mode.
- All passwords/credentials are stored on Host PC OS keyring, never on DUT.
