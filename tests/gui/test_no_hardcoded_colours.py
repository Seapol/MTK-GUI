"""M94: no widget may pin a colour in an inline stylesheet — pinned
colours are tuned for one theme and disappear in the others."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "mtkgui"
PATTERN = re.compile(r"setStyleSheet\([^)]*#[0-9a-fA-F]{3,8}")


def test_no_hex_colour_in_widget_stylesheets():
    offenders = []
    for path in sorted(ROOT.rglob("*.py")):
        if path.name == "style.py":
            continue
        for number, line in enumerate(path.read_text().splitlines(), 1):
            if PATTERN.search(line):
                offenders.append(f"{path.relative_to(ROOT.parent)}:{number}")
    assert offenders == [], "hard-coded colours: " + ", ".join(offenders)
