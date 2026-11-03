# -*- coding: utf-8 -*-
"""M62: automated layout audit sweep (offscreen, deterministic).

The whole GUI is audited exactly like ``python -m
mtkgui.gui.layout_audit``: the MainWindow first (that is what applies
the global QSS), then every :data:`WINDOW_FACTORIES` entry.  An issue
that is not in the known-issues whitelist fails the sweep - there is no
blanket suppression.

Windows whose factory needs a real service dependency are NOT skipped
here (that would break the suite skip baseline): the test asserts the
label is registered in :data:`SKIPPED_WINDOWS` and passes.
"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QDialog,
    QLineEdit,
    QVBoxLayout,
)

from mtkgui.gui import layout_audit  # noqa: E402
from mtkgui.gui.layout_audit import (  # noqa: E402
    WINDOW_FACTORIES,
    LayoutIssue,
    audit_widget,
    main,
    run_sweep,
)
from mtkgui.gui.layout_audit_known_issues import (  # noqa: E402
    SKIPPED_WINDOWS,
    is_whitelisted,
)
from mtkgui.style import APP_NAME, APP_ORG, build_qss, saved_theme  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module", autouse=True)
def isolated_settings(tmp_path_factory):
    """Keep the sweep independent of the developer's saved GUI state.

    MainWindow restores its window geometry and the console windows
    restore their own geometry from QSettings, which changes the
    MainWindow size hints between instances.  Every module that creates
    QSettings is pointed at an empty ini store so each measurement
    matches a fresh CLI run.
    """
    from pytest import MonkeyPatch

    import mtkgui.main_window as main_window_module
    import mtkgui.style as style_module
    import mtkgui.widgets.multi_console as multi_console_module

    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope,
                      str(tmp_path_factory.mktemp("m62-qsettings")))

    def _fresh_settings(*_args, **_kwargs):
        return QSettings(QSettings.IniFormat, QSettings.UserScope,
                         APP_ORG, APP_NAME)

    patcher = MonkeyPatch()
    for module in (style_module, main_window_module,
                   multi_console_module):
        patcher.setattr(module, "QSettings", _fresh_settings)
    try:
        yield
    finally:
        patcher.undo()


@pytest.fixture(scope="module")
def sweep(qapp, isolated_settings):
    """One full sweep, shared by every parametrized window assertion."""
    # parity with the CLI: MainWindow (the first audited root) normally
    # applies the saved theme; do it up front so geometry is identical
    # no matter which test the runner executes first.
    qapp.setStyleSheet(build_qss(saved_theme()))
    results, skipped = run_sweep(qapp)
    qapp.processEvents()
    # the sweep's windows persisted their geometry on close; reset so a
    # later MainWindow in this module measures the same fresh state
    QSettings(QSettings.IniFormat, QSettings.UserScope,
              APP_ORG, APP_NAME).clear()
    return results, skipped


def _new_issues(issues):
    return [issue for issue in issues if not is_whitelisted(issue)]


def _assert_clean(issues, label: str) -> None:
    new = _new_issues(issues)
    assert new == [], (
        f"{label}: {len(new)} layout issue(s) not in the known-issues "
        "whitelist\n" + "\n".join(str(issue) for issue in new))


# ------------------------------------------------- full-window sweep
@pytest.mark.parametrize(
    "label", [label for label, _ in WINDOW_FACTORIES],
    ids=[label for label, _ in WINDOW_FACTORIES])
def test_window_has_no_unwhitelisted_issue(sweep, label):
    results, skipped = sweep
    if label in skipped:
        # service-driven pages cannot be built with None; they are
        # registered as explicitly skipped instead of silently ignored
        assert label in SKIPPED_WINDOWS, (
            f"{label} crashed ({skipped[label]}) but is not registered "
            "in SKIPPED_WINDOWS")
        return
    _assert_clean(results[label], label)


# ------------------------------------------------------ MainWindow tabs
def test_main_window_every_page_is_clean(sweep):
    """Audit the shell and every tab page built by the sweep.

    The sweep (like the CLI) audits the MainWindow and then selects each
    tab page in turn; reusing its results keeps every measurement in
    this process identical to the first (fresh) MainWindow.
    """
    results, _ = sweep
    labels = [label for label in results
              if label == "MainWindow" or label.startswith("MainWindow/")]
    assert "MainWindow" in labels
    # the shell + the three tabs (Test Work Flow / Equipment / YAML Build)
    assert len(labels) >= 4, labels
    for label in labels:
        _assert_clean(results[label], label)


# --------------------------------------------------------- CLI smoke
def test_cli_exits_zero_for_a_clean_dialog(qapp, monkeypatch, capsys):
    dlg = QDialog()
    QVBoxLayout(dlg).addWidget(QLineEdit())
    edit = dlg.findChildren(QLineEdit)[0]
    edit.setText("ok")
    dlg.show()
    qapp.processEvents()
    try:
        assert audit_widget(dlg) == []
    finally:
        dlg.close()
        dlg.deleteLater()

    monkeypatch.setattr(layout_audit, "run_sweep", lambda app: ({}, {}))
    assert main([]) == 0
    assert "TOTAL 0 issues" in capsys.readouterr().out


def test_cli_exits_one_for_an_unwhitelisted_issue(monkeypatch, capsys):
    issue = LayoutIssue("clipped", "high", "MyWindow / QPushButton#Go",
                        "QPushButton", "width=40px < minimumSizeHint=72px")
    monkeypatch.setattr(
        layout_audit, "run_sweep",
        lambda app: ({"MyWindow": [issue]}, {}))
    assert main([]) == 1
    out = capsys.readouterr().out
    assert "TOTAL 1 issues (1 high / 0 low), 1 not whitelisted" in out


def test_whitelist_requires_the_exact_signature():
    """A new defect with the same path prefixes must still surface."""
    known = LayoutIssue("clipped", "high",
                        "EquipmentPage / QLabel#name",
                        "QLabel",
                        "width=130px < sizeHint=137px "
                        "(minimumSizeHint=137px)")
    assert is_whitelisted(known)
    new = LayoutIssue("clipped", "high",
                      "EquipmentPage / QLabel#name",
                      "QLabel",
                      "width=90px < sizeHint=137px (minimumSizeHint=137px)")
    assert not is_whitelisted(new)
    # a matching signature under an unrelated path is not tolerated
    assert not is_whitelisted(LayoutIssue(
        "clipped", "high", "Other / QLabel#name", "QLabel",
        "width=130px < sizeHint=137px (minimumSizeHint=137px)"))
