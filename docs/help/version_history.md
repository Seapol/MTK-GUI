# Version History

Release log of the MTK GUI. The GUI version starts at
**v1.0.0.0**; at any time the application carries exactly ONE
version - the current release version.

**Versioning rule** (user directive 2026-10-14):

- `develop` commits are NOT recorded in this log and do NOT bump
  the version - between releases the GUI keeps showing the current
  release version.
- A **Release** bumps the four-segment version number, gets its own
  git commit (Release commit), and records its changes as one entry
  in this file. The release entry is reviewed by the owner BEFORE
  the release is committed and published.

Entry format:

```text
## v<MAJOR>.<MINOR>.<PATCH>.<BUILD> - <YYYY-MM-DD>
- <change>
```

## v1.0.0.0 - 2026-10-14

- Initial release baseline of the MTK GUI versioning scheme.
- Feature set at baseline: ICT / FCT test execution engine with
  stop policies, breakpoints and Long Run; Yaml Build plan
  authoring (five-card block flow with embedded channel
  allocation, Excel import / export, Draft / Final publishing with
  archive); Equipment rack block diagram with
  DAQ973A / DAQM908A / DAQM907A / U2355A / N5747A; multi-channel
  serial / SSH console; Real-mode honesty (no simulation without a
  connected rack); DUT report / Event Log / Statistics; role and
  permission management; five GUI themes; Windows packaging via
  PyInstaller + GitHub Actions.

## Development milestones (not releases)

Engineering traceability only: these are `develop` commits. They do
NOT bump the version and do NOT change what the application reports
as its current release.

- **M6** (2026-10-23, `7a179b6`) - BOM import in Design Input
  (`design_input.bom_file`; the shared `ict/netparse/bom.py` library
  serves both the GUI and the headless CLI); the Control IO DIO pool
  moved to the U2355A `DIO01` - `DIO24` (24-channel capacity,
  over-capacity reported as `gpio=24 (+4 over capacity)`, DAQM907A
  DIO stays fixture-reserved); the unused `mtkgui/gui/designinput/`
  package removed.
- **M7** (2026-10-23, `e7930ef`) - `U2355A DIO Read` (reference level
  log, always `Done`) and `U2355A DIO Write` (drive with
  `Channels` + `Pattern`) standard operations; DIO Write isolation
  preflight with three notice levels (not isolated / cannot confirm /
  passive-only), `Cancel` + `Force-Continue` modal and headless
  refusal; netparse `isolated` / `active_drivers` evidence in CSV,
  JSON and the Test Plan evidence markdown; the old 24-channel
  walking GPIO template row removed from the Test Work Flow page.
