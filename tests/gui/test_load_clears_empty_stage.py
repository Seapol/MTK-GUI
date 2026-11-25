"""A plan that declares an empty stage must clear the previous one.

Loading project B over project A used to leave A's rows armed whenever B's
`ict_test_cases` / `fct_test_cases` list was empty: the loader only wrote
rows when there was something to write. The next run then executed a mix of
two projects. These tests pin the clear-on-empty contract; a missing key
still means "keep whatever the page has" so legacy files load as before.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from mtkgui import project_config
from mtkgui.permissions import ROLE_SUPERVISOR
from mtkgui.main_window import MainWindow


@pytest.fixture(scope="module")
def window():
    app = QApplication.instance() or QApplication([])
    win = MainWindow(role=ROLE_SUPERVISOR, mode="Virtual")
    yield win
    del app


def _plan(ict_names, fct_names):
    return {
        "project": {"core_id": "TEST", "part_number": "T-1"},
        "test_workflow": {
            "overall_flow": [{"stage": "ICT", "enable": bool(ict_names)},
                             {"stage": "FCT", "enable": bool(fct_names)}],
            "ict_test_cases": [
                {"name": n, "kind": "test", "enable": True, "unit": "V",
                 "threshold_min": "1.0", "threshold_max": "2.0"}
                for n in ict_names],
            "fct_test_cases": [
                {"name": n, "kind": "Message", "enable": True}
                for n in fct_names],
        },
    }


def test_empty_ict_list_clears_the_previous_rows(window):
    project_config.apply_config(_plan(["voltage A"], ["fct A"]),
                               window.workflow_page, window.equipment_page,
                               window.yaml_build_page.model)
    assert window.workflow_page.ict.rowCount() == 1

    project_config.apply_config(_plan([], ["fct B"]),
                               window.workflow_page, window.equipment_page,
                               window.yaml_build_page.model)
    assert window.workflow_page.ict.rowCount() == 0
    assert window.workflow_page.ict_steps == []
    assert window.workflow_page.ict_enables == []


def test_empty_fct_list_clears_the_previous_rows(window):
    project_config.apply_config(_plan(["voltage A"], ["fct A"]),
                               window.workflow_page, window.equipment_page,
                               window.yaml_build_page.model)
    assert window.workflow_page.fct.rowCount() == 1

    project_config.apply_config(_plan(["voltage B"], []),
                               window.workflow_page, window.equipment_page,
                               window.yaml_build_page.model)
    assert window.workflow_page.fct.rowCount() == 0
    assert window.workflow_page.fct_rows == []
    assert window.workflow_page.fct_enables == []


def test_missing_key_keeps_the_rows(window):
    """A legacy file without the key must not wipe the page."""
    project_config.apply_config(_plan(["voltage A"], ["fct A"]),
                               window.workflow_page, window.equipment_page,
                               window.yaml_build_page.model)
    legacy = _plan(["voltage A"], ["fct A"])
    legacy["test_workflow"].pop("fct_test_cases")
    project_config.apply_config(legacy, window.workflow_page,
                               window.equipment_page,
                               window.yaml_build_page.model)
    assert window.workflow_page.fct.rowCount() == 1
