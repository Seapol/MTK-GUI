# -*- coding: utf-8 -*-
"""M159c: board_role on the sequence model + five slave probe templates.

Each slave template is plain data that loads through the SHARED
template loader; every command it carries must come from the
SLAVE_PROBE_COMMANDS table in mtkgui/engine/fct_test_config.py.
"""
from __future__ import annotations

import os

from mtkgui.engine.fct_test_config import (
    SLAVE_PROBE_COMMANDS,
)
from mtkgui.engine.fct_templates import (
    SLAVE_TEMPLATE_LABELS,
    SLAVE_TEMPLATE_ROLES,
    load_template,
    load_template_commands,
    template_path,
)
from mtkgui.gui.yamlbuild.fct_build import (
    BOARD_ROLES,
    STEP_MESSAGE_CHECK,
    FctSequence,
    FctStep,
)


def _sequence_for(label):
    """Load one slave template and rebuild its FctSequence draft."""
    rows = load_template_commands(label)
    role = SLAVE_TEMPLATE_ROLES[label]
    steps = []
    for row in rows:
        assert row.send, f"{label}: row {row.name!r} carries no command"
        steps.append(FctStep(
            name=row.name,
            step_type=STEP_MESSAGE_CHECK,
            channel="ser1",
            command=row.send,
            expect_pass=([row.capture_expected]
                         if row.capture_expected else []),
            timeout_s=float(row.timeout or 30.0),
            params={"fct_console": True, "send_enabled": True,
                    "send": row.send,
                    "capture_enabled": bool(row.capture_expected)}))
    return FctSequence(name=label, board_role=role, steps=steps), rows


def test_five_slave_templates_parse_into_valid_sequences():
    assert len(SLAVE_TEMPLATE_LABELS) == 5
    for label in SLAVE_TEMPLATE_LABELS:
        assert os.path.isfile(template_path(label)), label
        data = load_template(label)
        assert data["steps"], label
        sequence, rows = _sequence_for(label)
        assert sequence.board_role in BOARD_ROLES
        assert sequence.validate() == [], label
        role = SLAVE_TEMPLATE_ROLES[label].split(":", 1)[1]
        allowed = SLAVE_PROBE_COMMANDS[role]
        for row in rows:
            assert row.send in allowed, (label, row.send)


def test_unknown_board_role_is_rejected():
    errors = FctSequence(name="probe", board_role="slave:gpu").validate()
    assert any("board_role" in error for error in errors)
    assert FctSequence(name="probe", board_role="slave:ssd").validate() == []
    assert FctSequence(name="probe", board_role="main").validate() == []


def test_main_role_keeps_todays_behaviour():
    steps = [FctStep(name="Boot banner", step_type=STEP_MESSAGE_CHECK,
                     channel="ser1")]
    sequence = FctSequence(name="FCT Sequence", steps=steps)
    assert sequence.board_role == "main"
    assert sequence.validate() == []
    assert sequence.to_dict()["board_role"] == "main"
    restored = FctSequence.from_dict(sequence.to_dict())
    assert restored.to_dict() == sequence.to_dict()
    # a pre-M159 document (no key) still loads as the main DUT
    legacy = FctSequence.from_dict({"name": "legacy"})
    assert legacy.board_role == "main"
