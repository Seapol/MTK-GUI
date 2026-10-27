
# FRDM-IMX93 FCT Setup Guide

## Board Info
- Model: NXP i.MX93 FRDM
- WiFi/BT: u-blox MAYA-W276 (NXP IW612)
- WiFi interface: mlan0 (station), uap0 (AP)
- BT interface: hci0

## 1. Load RF Drivers
Run this script after every boot:
```bash
/root/load_rf_drivers.sh
```

Expected output:
```
Loading WiFi...
WiFi mlan0 ready
Loading Bluetooth...
Bluetooth hci0 ready
RF drivers loaded OK
```

## 2. WiFi Station Mode (connect to router)

### 2.1 Configure wpa_supplicant
```bash
cat > /etc/wpa_supplicant.conf << EOF
network={
    ssid="YOUR_WIFI_SSID"
    psk="YOUR_WIFI_PASSWORD"
}
EOF
```

### 2.2 Connect and get IP
```bash
wpa_supplicant -B -i mlan0 -c /etc/wpa_supplicant.conf
udhcpc -i mlan0 -n -q
```

### 2.3 Verify connection
```bash
# Check IP
ip addr show mlan0

# Check RSSI
iw dev mlan0 link
# Look for: signal: -49 dBm
```

## 3. WiFi AP Mode (board as hotspot)
Use uap0 interface with hostapd (not configured yet).

## 4. Bluetooth

### 4.1 Check BT status
```bash
hciconfig hci0
# Should show: UP RUNNING
```

### 4.2 Make discoverable
```bash
hciconfig hci0 piscan
```

### 4.3 Scan nearby BT devices
```bash
hcitool scan
```

## 5. FCT Test Commands Reference

| Test | Command | Expected |
|------|---------|----------|
| WiFi RSSI | iw dev mlan0 link \| grep signal | signal: -XX dBm |
| Ping gateway | ping -c 20 192.168.10.1 | 0% packet loss |
| BT up | hciconfig hci0 | UP RUNNING |
| System | uname -a | Linux imx93frdm |

## 6. FAT Test Script
```bash
python3 /root/frdm_imx93_board_test/fat.py
# Type Y to start when prompted
```

## Files on Board
- /root/load_rf_drivers.sh - RF driver load script
- /root/frdm_imx93_board_test/fat.py - FAT test script
- /etc/wpa_supplicant.conf - WiFi config
