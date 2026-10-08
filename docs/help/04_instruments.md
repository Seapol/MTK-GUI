# Instruments & Connections

| Instrument | Role | Interface |
|---|---|---|
| DAQ973A mainframe | 6.5-digit DMM + 3 slots | GPIB / LAN / USB |
| DAQM908A #1 / #2 | 40-ch SE MUX each (impedance + voltage) | inside DAQ973A |
| DAQM907A | totalizer (clocks), AO, 16-ch DIO | inside DAQ973A |
| U2355A | 12-ch power-rails capture, counters, DIO | USB |
| N5747A | DC power supply (DUT power) | LAN |

Connection: Equipment page -> click the block -> choose interface /
address -> Test Connection -> Connect. Addresses come ONLY from the
project YAML / Equipment page (never hard-coded).
