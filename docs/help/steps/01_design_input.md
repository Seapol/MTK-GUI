## 01 · Design Input

This is the entry point. You define the project here - the five product fields, the ICT design files (or an Excel route) and the FCT test types. Every later node reads what you enter here, so node 02 only becomes editable once this node is locked.

![Design Input panel](images/06_yaml_design_input.png)

### Before you start

- Have the Allegro Smart PDF (SPF) and the netlist (NET) ready; the BOM is optional.
- Know the `Batch #` - it is required and marks a `Production` batch as production.

### Steps

1. Fill `Product Part #`, `Core ID`, `FSW Revision`, `700 HW Revision` and `Batch #`.
2. In `Design Files for ICT`, pick one route: `SPF + NET + BoM`, `ICT Excel Spreadsheet (Traditional)` or `MTK ICT Excel Sheet`.
3. For `SPF + NET + BoM`, press `Import SPF…`, then `Import NET…`, then `Import BOM…` when you have one. The status lines read `SPF: …`, `NET: …`, `BOM: …`.
4. For `ICT Excel Spreadsheet (Traditional)`, press `Import ICT Excel…`.
5. For `MTK ICT Excel Sheet`, press `Import MTK ICT Excel Sheet…`.
6. In `Pre-Configure for FCT`, pick `DUT Board Software` and tick the test types; `Select all` and `Select none` are shortcuts.
7. Press `Lock & Next: 02 · Parse nets for ICT` when the node is complete.

### Check before you lock

- At least one of ICT / FCT is enabled.
- The four product fields that are checked are filled, and `Batch #` is not empty.
- The selected ICT route carries its files: all three Route A files, the ICT Excel workbook, or the MTK ICT sheet.
- Locking node 01 also parses the Route A netlist, so node 02 opens with its tables already filled.

### If the node refuses to lock

- `At least one of ICT / FCT must be enabled` - turn one of the two blocks back on.
- `Product Part # is required` (or `Core ID`, `FSW Revision`, `700 HW Revision`) - fill the named field.
- `Batch # is required` - enter the lot name.
- `SPF, NET and BoM are all required` - import the missing Route A files.
- `ICT Excel Spreadsheet is required` / `MTK ICT Excel Sheet is required` - import the workbook of the selected route.
