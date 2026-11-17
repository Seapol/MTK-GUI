# -*- coding: utf-8 -*-
"""v2-2b: the flash-tool field and the GUI launcher survived the purge.

C2 deleted the flash-probe driver package and its block, but two pieces are
deliberately kept:

* the HOST PC ``Flash Tool Path`` row (``equipment_page.py``), because a
  3rd-party GUI flasher is still configured there;
* ``engine/flash_tool.py::launch_tool_gui`` - the detached GUI launcher the
  Flash_GUI step uses.

The test is Qt-free on purpose: it reads the two source files instead of
importing them, so it runs in the headless engine environment.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def test_flash_tool_field_row_kept():
    """The HOST PC config still offers the Flash Tool Path row."""
    text = (REPO / "mtkgui" / "equipment_page.py").read_text(encoding="utf-8")
    assert re.search(
        r'\("flash_tool",\s*"Flash Tool Path",\s*""\)', text), \
        "the ('flash_tool', 'Flash Tool Path') row is gone"


def test_launch_tool_gui_kept():
    """The detached third-party GUI launcher keeps its signature."""
    text = (REPO / "mtkgui" / "engine" / "flash_tool.py").read_text(
        encoding="utf-8")
    assert re.search(
        r"def launch_tool_gui\(exe: str\) -> tuple\[bool, str\]:", text), \
        "launch_tool_gui(exe: str) -> tuple[bool, str] is gone"
