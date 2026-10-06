# -*- coding: utf-8 -*-
"""Real-world Allegro export self-tests (project 96317 sample files).

The user-supplied standard Allegro exports: an "Allegro Report" CSV
net list (NET-96317_A.net) and a real Smart-PDF drawing
(SPF-96317_a.pdf - the PDF itself is 7.6 MB and stays OUT of the
repo; its extracted-text excerpt is embedded here for the title
extraction test)."""
from __future__ import annotations

from pathlib import Path

from mtkgui.gui.yamlbuild.dual_format import (  # noqa: E402
    detect_netlist_format,
    parse_netlist_auto,
)
from mtkgui.gui.yamlbuild.parser import (  # noqa: E402
    core_id_from_filename,
    extract_drawing_board_name,
)
from mtkgui.gui.yamlbuild.parse_nets import (  # noqa: E402
    parse_testable_nets,
)
from mtkgui.gui.yamlbuild.test_points import (  # noqa: E402
    select_test_points,
)

FIXTURE = Path(__file__).parent / "fixtures" / "NET-96317_A.net"

# excerpt of the real Smart-PDF extracted text (title block area):
# the board name sits next to the "Rev." block
PDF_EXCERPT = """\x0c\x05\r\x0e\x0f\x0e\x07\n\x06\x10\x0e\x0f\x0b\x07\x11\x12\r
Rev. Code Date DescriptionBy
FRDM-IMXRT700
1. Unless Otherwise Specified:
All resistors are in ohms, 1/16 Watt,0402
2026-04-08 James Fan Initialize release
System Power 2
"""


def test_real_net_file_detected_as_allegro_report():
    text = FIXTURE.read_text(encoding="utf-8")
    assert detect_netlist_format(text) == "allegro_report"


def test_real_net_file_parses_fully():
    """The blocking bug: a standard Allegro report NET file MUST
    parse without 'no nets found'."""
    result = parse_testable_nets(FIXTURE.read_text(encoding="utf-8"))
    assert result.total == 70
    # classification: 2 power / 2 SE clock / 64 signal candidates,
    # the two reference grounds filtered
    assert len(result.power) == 2
    assert {r.name for r in result.power} == \
        {"5V_SDA_PSW", "5V_USB0_OTG"}
    assert {r.name for r in result.clock} == \
        {"DBGIF_TCK_SWCLK", "DMIC_CLK"}
    assert len(result.gpio) == 64
    assert {n for n, _r in result.filtered} == {"AGND", "GND"}
    # members map 1:1 (spot check)
    spot = next(r for r in result.gpio if r.name == "CORTEX7")
    assert spot.members == ["J18.7", "TP20.1"]


def test_real_net_file_test_point_selection():
    """Step 4 on real data: TP beats the J pin on CORTEX7; J wins
    where no TP exists (FXIO_D1)."""
    result = parse_testable_nets(FIXTURE.read_text(encoding="utf-8"))
    cortex7 = next(r for r in result.gpio if r.name == "CORTEX7")
    assert select_test_points(cortex7.members)[0] == "TP20.1"
    fxio = next(r for r in result.gpio if r.name == "FXIO_D1")
    assert select_test_points(fxio.members)[0] == "J53.7"


def test_real_pdf_title_extraction():
    """The Smart-PDF drawing title yields the board Project Part#
    (FRDM-IMXRT700); the Core ID comes from the file name."""
    assert extract_drawing_board_name(PDF_EXCERPT) == "FRDM-IMXRT700"
    assert core_id_from_filename("SPF-96317_a.pdf") == "96317"


def test_real_net_and_pdf_no_cross_deviation():
    """Dual-format guarantee: the parsed NET connectivity is the
    single source - re-parsing is deterministic (same result twice)."""
    text = FIXTURE.read_text(encoding="utf-8")
    first = parse_testable_nets(text)
    second = parse_testable_nets(text)
    assert first.summary() == second.summary()
    assert [r.name for r in first.power] == \
        [r.name for r in second.power]
    assert [r.members for r in first.gpio] == \
        [r.members for r in second.gpio]
