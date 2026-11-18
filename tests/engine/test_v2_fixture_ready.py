# -*- coding: utf-8 -*-
"""v2-9a: ONE fixture verdict replaces the five per-signal operations.

The fixture is judged, never commanded: every signal that is both
``used`` and ``enabled`` in ``equipment.fixture.signals`` must hold, and
two reads ``debounce_ms`` apart must agree.  A project YAML that still
carries one of the five retired rows is refused by name.
"""
from __future__ import annotations

from types import SimpleNamespace

from mtkgui.engine import yaml_validation as yv
from mtkgui.engine.instruments import RealGateway
from mtkgui.engine.steps import (FIXTURE_OPS, RETIRED_FIXTURE_OPS,
                                 retired_fixture_op_message)

_SIGNALS = {
    "clamped": {"port": 1, "bit": 0, "used": True, "enabled": True,
                "label": "Clamped"},
    "inpos": {"port": 1, "bit": 1, "used": True, "enabled": True,
              "label": "In position"},
    "presence": {"port": 1, "bit": 2, "used": True, "enabled": True,
                 "label": "DUT presence"},
    "estop": {"port": 1, "bit": 3, "used": True, "enabled": True,
              "label": "E-stop"},
}

EQUIPMENT = {"fixture": {"signals": _SIGNALS}}


class _FakeDAQ:
    """Scripted DAQM907A DIO: one value per read call, in call order."""

    def __init__(self, values):
        self._values = list(values)
        self.calls: list = []

    def read_dio(self, channel):
        self.calls.append(channel)
        return SimpleNamespace(value=self._values.pop(0))


def _gateway(values, fixture_type="ATE"):
    gw = RealGateway(EQUIPMENT, fixture_type=fixture_type)
    fake = _FakeDAQ(values)
    gw._drivers["daq973a"] = fake
    return gw, fake


def _run(gw):
    return gw.execute_op("Fixture Ready",
                         {"type": "fixture_ready", "debounce_ms": 0})


#: healthy logical levels across the enabled conditions (canonical order:
#: clamped, inpos, presence, estop) - two identical debounce passes
_HEALTHY = [1, 1, 0, 0, 1, 1, 0, 0]


def test_fixture_ready_reports_state():
    gw, fake = _gateway(_HEALTHY)
    out = _run(gw)
    assert out.verdict == "Done"
    assert out.text == "FIXTURE READY"
    assert len(fake.calls) == 8          # four signals, two reads each
    assert set(fake.calls) == {"DIO01", "DIO02", "DIO03", "DIO04"}


def test_fixture_ready_names_the_failing_condition():
    gw, _fake = _gateway([0, 1, 0, 0,       # pass 1: clamped reads 0
                          0, 1, 0, 0])      # pass 2: same -> stable
    out = _run(gw)
    assert out.verdict == "Error"
    assert out.text == "NOT READY - clamped"
    assert out.lines[0] == "NOT READY - clamped"


def test_fixture_ready_needs_two_matching_reads():
    gw, _fake = _gateway([1, 1, 0, 0,       # pass 1: healthy
                          0, 1, 0, 0])      # pass 2: clamped dropped
    out = _run(gw)
    assert out.verdict == "Error"
    assert out.text == ""
    assert out.lines[0] == \
        "Fixture state is not stable - re-seat the board"


def test_fixture_ready_is_absent_under_manual():
    # the canonical sequence builder emits the single verdict, never a
    # per-signal movement row
    from mtkgui.gui.yamlbuild.ict_sequence import standard_ict_sequence
    names = [row[1] for row in standard_ict_sequence([], 0)
             if row[0] == "op"]
    assert "Fixture Ready" in names
    assert not set(names) & set(RETIRED_FIXTURE_OPS)
    assert FIXTURE_OPS == ("Fixture Ready",)
    # a hand-written row on a Manual project is an Error, never a
    # silent "no hardware action"
    gw, fake = _gateway(_HEALTHY, fixture_type="Manual")
    out = _run(gw)
    assert out.verdict == "Error"
    assert out.lines[0] == ("Fixture Ready needs an ATE fixture - this "
                            "project logs in as Manual")
    assert fake.calls == []


def test_retired_fixture_op_is_refused():
    doc = {"test_workflow": {
        "ict_test_cases": [{"name": "Fixture Clamp Down", "kind": "op"}],
        "fct_test_cases": [],
    }}
    issues = [issue for issue in yv.validate_project_yaml(doc)
              if "Fixture Clamp Down" in issue.message]
    assert len(issues) == 1
    issue = issues[0]
    assert issue.severity == yv.SEVERITY_ERROR
    assert issue.message == retired_fixture_op_message("Fixture Clamp Down")
    assert issue.location == "ict_test_cases[0].name"
    assert yv.blocking_issues(yv.validate_project_yaml(doc))
