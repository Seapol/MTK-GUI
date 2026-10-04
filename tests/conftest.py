# -*- coding: utf-8 -*-
"""Root test fixtures (P2-1, test-only — zero product-code change).

Creates ONE QApplication for the whole session before any test runs.
Engine demo code needs a QCoreApplication; when the GUI tests run in the
same process they need a full QApplication.  QApplication IS a
QCoreApplication subclass, so building it first satisfies both and
avoids the Qt abort from mixing the two app types in one process.
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _qapp_session():
    QApplication.instance() or QApplication([])
    yield
