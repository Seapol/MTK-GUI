# Page Guide

- **Test Work Flow**: run control, Overall Flow (ICT/FCT enable),
  product info, per-step tables, power-rails waveform, console.
- **Equipment**: instrument block diagram; click a block to configure
  and connect (interface / address / parameters / Test Connection).
- **Yaml Build** (12-stage block flow):
  - *Design Input*: SPF / NET files, product metadata.
  - *Parse nets for ICT*: three-category parse (Power / Clock / GPIO),
    Filtered table with reasons.
  - *Channel Allocation*: per-category dropdown allocation; nets
    WITHOUT a channel are auto Do-Not-Test.
  - *Configure Instruments*: per-instrument Connect / Disconnect
    (same kernel as Tools > Set All instruments).
  - *Rails / Clocks / GPIO*: capture + sequence parameters.
  - *Build FCT Test Work Flow Sequence*: FCT sequence skeleton.
  - *Validate*: full-sequence validation - a passed block gets a check.
  - *Publish*: Draft / Final plan YAML with compliant naming.
- **Channel Allocation**: the dedicated three-tab allocation page.
- **Console** (embedded in the Test Work Flow page): multi-channel
  serial / SSH consoles, quick commands, pop-out windows; the FCT
  message tests read the channel buffers.
- Every configured block gets a star; Validate turns stars into checks.
