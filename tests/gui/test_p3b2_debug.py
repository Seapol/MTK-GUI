# -*- coding: utf-8 -*-
"""P3-B2 T4 workflow-debug tests: breakpoints and single-step run.

The debug feature lives entirely in the GUI layer: it drives the
engine only through the public pause()/resume() API at safe step
boundaries (the runner state machine itself is not modified).  The
tests drive the runner the same way tests/engine/test_runner.py does:
manual _run_step() boundary ticks, no real event loop."""
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
    w = TestWorkFlowPage()
    # Virtual mode: no real instruments, simulated DUT answers, no
    # modal operator dialogs (the debug tests run without an event
    # loop except the processEvents calls in the tick helper)
    w.virtual_mode = True
    w.multi_console.set_virtual_mode(True)
    w._runner.fct_connect_timeout = 5.0
    # Message* FCT rows would open a modal operator dialog (blocks the
    # offscreen tests): simulate the operator answer instead
    w._fct_message_dialog = lambda kind, name: "PASS"
    # shorten the FCT console wait rows (no simulated DUT worker behind
    # the channel in this environment) so the runs stay fast
    w.fct_timeouts = [600] * len(w.fct_timeouts)
    yield w
    # deterministic teardown: end the run, stop the virtual worker
    # threads and flush pending events (a dangling QThread would abort
    # the whole test process on interpreter shutdown)
    try:
        w._runner.abort()
    except RuntimeError:
        pass
    w.multi_console.close_all_channels()
    qapp.processEvents()
    w.deleteLater()
    qapp.processEvents()


def _run_while_running(page, max_ticks=3000):
    """Manually tick the runner until it leaves 'running' (paused /
    idle / aborted / frozen) or the tick budget is exhausted.  Sparse
    processEvents calls deliver the queued worker signals (virtual DUT
    replies, console connection changes) and fire the run timer, like
    a real GUI session would."""
    from PySide6.QtWidgets import QApplication

    runner = page._runner
    for i in range(max_ticks):
        if runner.state != "running":
            break
        runner._run_step()
        if i % 5 == 0:
            QApplication.processEvents()
    return runner.state


# ------------------------------------------------------------ breakpoints
def test_breakpoint_pauses_after_node(page):
    """A breakpointed ICT node pauses the run right after the node
    completes (engine parked in 'paused' at the safe boundary)."""
    seen = []
    page._runner.step_finished.connect(
        lambda i, r: seen.append(i))
    # row 0 is 'Init Instruments' (op step): breakpoint on it
    page.ict_breakpoints.add(0)
    page._runner.start(1)
    state = _run_while_running(page)
    assert state == "paused"
    assert seen, "no step executed before the pause"
    page._runner.abort()


def test_breakpoint_no_hit_runs_through(page):
    """Without breakpoints (and without step mode) a run completes
    without pausing."""
    page._runner.start(1)
    state = _run_while_running(page)
    assert state == "idle"
    assert page._runner.state == "idle"


# ------------------------------------------------------------ single step
def test_step_mode_executes_one_node_per_press(page):
    """Step mode: exactly one more workflow node executes per press,
    then the engine pauses again; Continue finishes the run."""
    seen = []
    page._runner.step_finished.connect(
        lambda i, r: seen.append(i))
    # arm the single-step mode before the run: the first node already
    # pauses the engine after completing
    page._step_mode = True
    page._runner.start(1)
    state = _run_while_running(page)
    assert state == "paused"
    n_after_first = len(seen)

    # one Step press = exactly one more node, paused again
    page.debug_step()
    assert page._runner.state == "running"
    state = _run_while_running(page)
    assert state == "paused"
    assert len(seen) == n_after_first + 1

    # second Step press: one more node again
    page.debug_step()
    state = _run_while_running(page)
    assert state == "paused"
    assert len(seen) == n_after_first + 2

    # Continue: the run completes without further pauses
    page.debug_continue()
    state = _run_while_running(page)
    assert state == "idle"
    assert len(seen) > n_after_first + 2


def test_step_button_from_running_pauses_then_steps(page):
    """Pressing Step while running parks the engine after the current
    node (single-step armed from the running state)."""
    page._runner.start(1)
    page._runner._run_step()          # advance at least one tick
    if page._runner.state != "running":
        pytest.skip("run left the running state on the first tick")
    page.debug_step()
    state = _run_while_running(page)
    assert state == "paused"
    page._runner.abort()


def test_continue_without_pause_is_noop(page):
    """Continue outside a paused debug session does not raise."""
    page.debug_continue()
    assert page._runner.state == "idle"


def test_step_continue_disabled_outside_run(page):
    """The debug buttons start disabled and enable per engine state."""
    assert not page.btn_step.isEnabled()
    assert not page.btn_continue.isEnabled()


# ------------------------------------------------------ breakpoint markers
def test_toggle_breakpoint_marks_row(page):
    """The context-menu toggle stores the row and marks the '#' cell;
    toggling again clears both."""
    page._toggle_breakpoint(page.ict, 3, page.ict_breakpoints)
    assert 3 in page.ict_breakpoints
    item = page.ict.item(3, 0)
    assert item.text() == "● 4"
    assert item.toolTip().startswith("breakpoint")
    page._toggle_breakpoint(page.ict, 3, page.ict_breakpoints)
    assert 3 not in page.ict_breakpoints
    assert page.ict.item(3, 0).text() == "4"
    assert page.ict.item(3, 0).toolTip() == ""


def test_fct_breakpoint_pauses(page):
    """A breakpointed FCT row pauses during the FCT stage."""
    page.fct_breakpoints.add(0)
    page._runner.start(1)
    state = _run_while_running(page)
    assert state == "paused"
    page._runner.abort()


def test_context_menu_offers_breakpoint(page):
    """Both tables carry the 'Breakpoint' context-menu entry."""
    import inspect
    assert "Breakpoint" in inspect.getsource(page._ict_context_menu)
    assert "Breakpoint" in inspect.getsource(page._fct_context_menu)


def test_no_engine_files_modified_for_debug():
    """Boundary guard: the debug feature must not touch the core
    engine sources (GUI-layer only, runner used via public API)."""
    import inspect
    import mtkgui.engine.runner as runner_mod
    src = inspect.getsource(runner_mod)
    assert "breakpoint" not in src.lower()
    assert "step_mode" not in src.lower()
