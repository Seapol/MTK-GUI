"""M129: node 02 shows Parsed Nets and Other Nets side by side."""

from __future__ import annotations

from mtkgui.gui.yamlbuild.parse_nets_v2_panel import ParseNetsV2Panel


def test_parsed_and_other_nets_sit_in_two_columns():
    panel = ParseNetsV2Panel()
    try:
        panel.resize(980, 420)
        panel.show()
        panel.layout().activate()

        left = panel.table.geometry()
        right = panel.table_other.geometry()
        assert left.right() < right.left(), "tables must not overlap"
        assert abs(left.top() - right.top()) <= 6, \
            "the two tables share one row (left/right layout)"
        assert left.width() > left.height(), "tables are wider than tall"
        assert right.width() > right.height(), "tables are wider than tall"
    finally:
        panel.deleteLater()
