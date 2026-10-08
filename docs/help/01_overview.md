# Overview

MTK GUI is a cross-platform manufacturing test tool covering the complete
production flow:

    ICT -> Flash FAT firmware -> FCT -> Flash OOBE firmware

- **ICT** (In-Circuit Test): fixture interlocks, impedance shorts,
  power-on, power-rails capture, DC voltage, clocks, GPIO.
- **Flash FAT**: factory acceptance firmware, flashed by a third-party
  GUI (operator confirm) or a CLI (automatic keyword parse).
- **FCT** (Functional Test): message testing - the verdict comes from
  Pass/Success vs Fail/Error keywords in the channel output, an
  operator dialog, or a CLI result.
- **Flash OOBE**: out-of-box-experience firmware, same dual path.

The Test Work Flow page renders the whole flow as one table; the
Yaml Build page (12-stage block flow) authors the project.
