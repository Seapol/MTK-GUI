# -*- coding: utf-8 -*-
"""M101: Test Work Flow page review (2x2 body, float/dock tables, Console
tabs + Command Helper, status-bar progress width)."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from mtkgui.test_workflow_page import TestWorkFlowPage  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def page(qapp):
    p = TestWorkFlowPage()
    yield p
    p.deleteLater()


def test_fct_default_rows_drop_flash_gui_suffix(page):
    names = list(page.fct_rows)
    assert "MessageGoStop: Flash FAT Firmware" in names
    assert "MessageGoStop: Flash OOBE Firmware" in names
    assert not any("(3rd-party GUI)" in n for n in names)
