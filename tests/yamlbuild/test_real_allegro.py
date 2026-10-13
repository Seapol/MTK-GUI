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
    # classification: 10 power / 2 SE clock / 28 signal candidates;
    # the two reference grounds are GND rows (default Do Not Test).
    # The Exclude Parse Nets regex drops the UART / WAKE / RESET /
    # I2C / DATA / DBGIF signal nets (28, factory default: DIFF /
    # RESET/ENABLE/UART/WAKE/I2C/SPI/JTAG/DBGIF/DATA/ADC + random
    # numeric names)
    assert {r.name for r in result.power} == {
        "5V_SDA_PSW", "5V_USB0_OTG", "CODEC_1V8", "CPVOUTN",
        "CPVOUTP", "DBGIF_VREF", "DCDC_1V0", "DCDC_1V8",
        "DCDC_3V3", "DC_5V_IN"}
    assert {r.name for r in result.clock} == \
        {"DBGIF_TCK_SWCLK", "DMIC_CLK"}
    assert len(result.gpio) == 28
    assert {r.name for r in result.gnd} == {"AGND", "GND"}
    assert all(reason.startswith("excluded by")
               for _n, reason in result.filtered)
    assert len(result.filtered) == 28
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


# excerpt structure of the project 97122 Smart-PDF (2026-10-13):
# the board name X-RING-OPTIC-ETH repeats on EVERY page footer while
# the MOSFET part number BUK9M3R3-40HX appears only next to its
# refdes instances (Q15..) - and the board name starts with a SINGLE
# letter, which the old first-group>=2 pattern rejected
PDF_97122_EXCERPT = """\x0c
C C
B B
A A
X-RING-OPTIC-ETH
ALL SILK SHOWN IN THIS COLOR
Date
Intial Draft
Page Title:
Classification:
SCH-97122 / PDF: SPF-97122 A
X-RING-OPTIC-ETH
C
Tuesday, August 25, 2026
01 - Title Page
Page Title:
SCH-97122 / PDF: SPF-97122 A
X-RING-OPTIC-ETH
C
Tuesday, August 25, 2026
02 - Block Diagram
R996 0
Q16
BUK9M3R3-40HX
5
4
1
Q17
BUK9M3R3-40HX
5
4
1
SCH-97122 / PDF: SPF-97122 A
X-RING-OPTIC-ETH
C
Tuesday, August 25, 2026
04 - S32K566 POWER
"""


def test_pdf_title_beats_component_part_number():
    """Project 97122 (user report): the per-page title-block name
    (X-RING-OPTIC-ETH, single-letter first group) must win over the
    sparse component part number (BUK9M3R3-40HX) - frequency ranking
    + relaxed first group."""
    assert extract_drawing_board_name(PDF_97122_EXCERPT) == \
        "X-RING-OPTIC-ETH"


# excerpt structure of the OLD project 29420 drawing (non-standard):
# no per-page footer board name - the title block INDEX lists several
# boards as "Schematic SCH-<id> / Part No. <name>" pairs; THIS file
# (core id 29420) pairs with MCIMX8QM-CPU.  The only STANDALONE
# board-name-shaped lines are component values (the eMMC), which the
# frequency ranking would wrongly pick without the SCH pairing layer.
PDF_29420_EXCERPT = """\x0c
D D
C C
MCIMX8QM-CPU MEK Platform
Schematic capture done with Allegro Design Entry CIS 17.2.
I2C TABLE Part Number: MCIMX8QM-CPU
01 FRONT PAGE
i.MX 8QM CPU Card
Schematic SCH-29420
Part No. MCIMX8QM-CPU
i.MX 8QXP CPU Card
Schematic SCH-29683
Part No. MCIMX8QXP-CPU Common Base Board
Schematic SCH-29918
Part No. MCIMX8-8X-BB
LVDS TO HDMI Daughter Card
Schematic SCH-29680
Part No. IMX-LVDS-HDMI
MIPI TO HDMI Daughter Card
LPDDR4
eMMC
MTFC32GAZAQHD-AIT
PMIC2
eMMC
MTFC32GAZAQHD-AIT
"""


def test_labelled_part_no_paired_with_file_core_id():
    """Project 29420 (user report): the old drawing carries no
    standalone board name - the "Part No. <name>" entry whose SCH
    number matches the FILE-NAME core id (29420) wins outright over
    the standalone component values (frequency ranking would pick
    the eMMC part number)."""
    assert extract_drawing_board_name(PDF_29420_EXCERPT,
                                      core_id="29420") == "MCIMX8QM-CPU"
    # WITHOUT the core id the SCH pairing is off and the frequency
    # ranking applies (documented fallback behavior)
    assert extract_drawing_board_name(PDF_29420_EXCERPT) == \
        "MTFC32GAZAQHD-AIT"


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
