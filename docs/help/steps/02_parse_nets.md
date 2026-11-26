## 02 · Parse nets for ICT

This step turns the netlist into test categories. The left table holds the nets the classifier recognised (power / clock / ground), the right table holds the unclassified ones; node 05 seeds its ICT sequence from the result.

![Parse nets for ICT](images/07_yaml_parse_nets.png)

### Before you start

- Node 01 is locked with a Route A netlist (`SPF + NET + BoM`) - locking it already runs the first parse.
- On `MTK ICT Excel Sheet` (Route C) this node is skipped and opens read-only, so there is nothing to do here.

### Steps

1. Open the node and read the summary line under the two tables, e.g. `Power 82 · SE Clock 20 · GND 4 · Other 2124 · skipped 0 rows`.
2. Review the `Parsed Nets` table: every row carries `Net Name`, `Category`, `Sub-type`, `Test Point`, `Nominal`, `Limits` and `Confidence`.
3. Move a net between the tables with its `Category` dropdown - no re-parse is needed for that.
4. Keep the consumption order with `Move Up` / `Move Down`.
5. Press `Parse nets` only when the NET file changed outside the tool; the run shows a percentage bar with the parser stages.

### Check before you lock

- Locking accepts the current table content; the parse result is already written into the model as it is produced, so node 05 seeds from the latest parse.
- DNP parts leave the `Power` bucket once a BOM is applied, because they are not testable on the fixture.
- The five summary numbers are recomputed from the file on each parse and add up to the netlist.

### If the node refuses to lock

- `Parse failed: …` - the netlist could not be read. The warning names the file (`File: <path>`); re-import the NET file on node 01, then press `Parse nets` again.
