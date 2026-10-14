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
