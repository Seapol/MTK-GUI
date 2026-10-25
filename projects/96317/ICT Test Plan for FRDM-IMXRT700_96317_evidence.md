# ICT Test Plan evidence - FRDM-IMXRT700_96317

- source: 
- format: allegro_report
- generated_at: 2026-10-22T21:55:56
- total nets: 70

## Category counts

- power: 10
- clock: 1
- control_io: 5
- others: 23
- gnd: 2
- filtered: 29

## Capacity usage

- power: 10/80 (R-GND+Voltage)
- rails-up: 10/12 (input_rails first)
- clock: LF 0/1, HF 1/2
- control_io: 5/24
- gnd: 2 reference plane(s) - not counted

## Input rails

- DC_5V_IN
  evidence: DC_5V_IN: rule:power

## Bridge merges

- (none)

## External rules applied

- (none)

- nominal: nominal from net-name heuristic - confirm in Power-Tree Editor

## Power

### DC_5V_IN
- category: Power
- confidence: low
- sub_class: 
- provenance: rule:power
- input_rail: true
- test_point: TP72.1 J45.1 C642.1 R33.1 F1.1
- nominal: 5 V

### 5V_SDA_PSW
- category: Power
- confidence: high
- sub_class: 
- provenance: rule:power
- test_point: C48.1 D43.A
- nominal: 5 V

### 5V_USB0_OTG
- category: Power
- confidence: high
- sub_class: 
- provenance: rule:power
- test_point: TP89.1 SJ314.1 C230.1 L25.2 R379.1 D42.A
- nominal: 5 V

### DCDC_3V3
- category: Power
- confidence: medium
- sub_class: 
- provenance: rule:power
- test_point: TP37.1 J53.2 JP11.3 C242.1 L1.2 R292.1 Q19.2
- nominal: 3.3 V

### CODEC_1V8
- category: Power
- confidence: medium
- sub_class: 
- provenance: rule:power
- test_point: SJ216.2 C96.1 U29.C6
- nominal: 1.8 V

### DCDC_1V8
- category: Power
- confidence: medium
- sub_class: 
- provenance: rule:power
- test_point: TP88.1 JP5.3 C379.1 L30.2 R544.1 U75.1
- nominal: 1.8 V

### DCDC_1V0
- category: Power
- confidence: medium
- sub_class: 
- provenance: rule:power
- test_point: TP87.1 SJ374.2 C384.1 L715.2 R3052.1
- nominal: 1 V

### CPVOUTN
- category: Power
- confidence: low
- sub_class: 
- provenance: rule:power
- test_point: C93.1 U29.A7

### CPVOUTP
- category: Power
- confidence: low
- sub_class: 
- provenance: rule:power
- test_point: C92.1 U29.A6

### DBGIF_VREF
- category: Power
- confidence: low
- sub_class: 
- provenance: rule:power
- test_point: C11.1 R54.2 U8.L1

## SE-Clock

### DMIC_CLK
- category: SE-Clock
- confidence: medium
- sub_class: 
- provenance: rule:se_clock
- test_point: SJ210.1 U66.4

## Control IO

### 154_RST
- category: Control IO
- confidence: high
- sub_class: 
- provenance: control_io:reset
- test_point: U68.56

### BT_154_RST
- category: Control IO
- confidence: high
- sub_class: 
- provenance: control_io:reset
- test_point: U68.67

### BT_RST
- category: Control IO
- confidence: high
- sub_class: 
- provenance: control_io:reset
- test_point: U68.62

### BOOT_ISP0
- category: Control IO
- confidence: low
- sub_class: 
- provenance: control_io:mode
- test_point: R155.1 SW10.2

### BOOT_ISP1
- category: Control IO
- confidence: low
- sub_class: 
- provenance: control_io:mode
- test_point: R157.2 SW10.1

## GND

- AGND (pcb)
- GND (pcb)

## Others

- AUD_INT: unclassified (fallback:unclassified)
- CCC_INTB_1V8: unclassified (fallback:unclassified)
- CCC_INTB_3V3: unclassified (fallback:unclassified)
- CORTEX7: unclassified (fallback:unclassified)
- CORTEX9: unclassified (fallback:unclassified)
- CPCA: unclassified (fallback:unclassified)
- CPCB: unclassified (fallback:unclassified)
- FXIO_D0: unclassified (fallback:unclassified)
- FXIO_D1: unclassified (fallback:unclassified)
- FXIO_D2: unclassified (fallback:unclassified)
- FXIO_D3: unclassified (fallback:unclassified)
- FXIO_D4: unclassified (fallback:unclassified)
- FXIO_D5: unclassified (fallback:unclassified)
- FXIO_D6: unclassified (fallback:unclassified)
- FXIO_D7: unclassified (fallback:unclassified)
- FXIO_D8: unclassified (fallback:unclassified)
- FXIO_D9: unclassified (fallback:unclassified)
- FXIO_D10: unclassified (fallback:unclassified)
- FXIO_D11: unclassified (fallback:unclassified)
- FXIO_D12: unclassified (fallback:unclassified)
- FXIO_D13: unclassified (fallback:unclassified)
- FXIO_D14: unclassified (fallback:unclassified)
- FXIO_D15: unclassified (fallback:unclassified)

## Filtered

- BRG_I2C0_SCL: excluded by Exclude Parse Nets regex
- BRG_I2C0_SDA: excluded by Exclude Parse Nets regex
- BT_154_WAKE_OUT: excluded by Exclude Parse Nets regex
- BT_DEV_WAKE: excluded by Exclude Parse Nets regex
- BT_UART_CTS: excluded by Exclude Parse Nets regex
- BT_UART_RTS: excluded by Exclude Parse Nets regex
- BT_UART_RXD: excluded by Exclude Parse Nets regex
- BT_UART_TXD: excluded by Exclude Parse Nets regex
- CODEC_I2C3_SCL: excluded by Exclude Parse Nets regex
- CODEC_I2C3_SDA: excluded by Exclude Parse Nets regex
- DBGIF_DETECT: excluded by Exclude Parse Nets regex
- DBGIF_ISP0_CTRL: excluded by Exclude Parse Nets regex
- DBGIF_ISP1_CTRL: excluded by Exclude Parse Nets regex
- DBGIF_ISP2_CTRL: excluded by Exclude Parse Nets regex
- DBGIF_RESET: excluded by Exclude Parse Nets regex
- DBGIF_RESET_TXEN: excluded by Exclude Parse Nets regex
- DBGIF_TCK_SWCLK: excluded by Exclude Parse Nets regex
- DBGIF_TDI: excluded by Exclude Parse Nets regex
- DBGIF_TDO_SWO: excluded by Exclude Parse Nets regex
- DBGIF_TMS_SWDIO: excluded by Exclude Parse Nets regex
- DBGIF_TMS_SWDIO_TXEN: excluded by Exclude Parse Nets regex
- DMIC_DATA01: excluded by Exclude Parse Nets regex
- DMIC_DATA23: excluded by Exclude Parse Nets regex
- DMIC_DATA45: excluded by Exclude Parse Nets regex
- DMIC_DATA67: excluded by Exclude Parse Nets regex
- DMIC_I2C3_SCL: excluded by Exclude Parse Nets regex
- DMIC_I2C3_SDA: excluded by Exclude Parse Nets regex
- FC3_I2C3_SCL: excluded by Exclude Parse Nets regex
- FC3_I2C3_SDA: excluded by Exclude Parse Nets regex

## Power tree flows

(rank order: input rails first)

0. DC_5V_IN (INPUT)
1. 5V_SDA_PSW
2. 5V_USB0_OTG
3. DCDC_3V3
4. CODEC_1V8
5. DCDC_1V8
6. DCDC_1V0
7. CPVOUTN
8. CPVOUTP
9. DBGIF_VREF
