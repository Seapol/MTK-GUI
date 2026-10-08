# Test Items

- **Static Impedance** (Omega, 2-wire): shorts catch before power.
- **Power Voltage**: DCV per rail within +/-0.1%.
- **Clock Hz**: totalizer frequency checks.
- **Power Rails Up Sequence** (DAQ AI): U2355A capture, CSV + waveform,
  AI waveform review.
- **MESSAGE_CHECK / MessageOK / YesNo / GoStop**: operator dialogs.
- **CapturefromConsole / SendtoCLI**: channel keyword judgement
  (negative-wins rule - any Fail/Error keyword beats a later Pass).
- **GUI_CONFIRM**: third-party GUI flow + human GO / STOP.
- **EXTERNAL_TOOL / WIFI / Bluetooth**: RF via CLI or vendor tool
  (iperf3, wifi_test, bt_test) - same message parsing.
