# -*- coding: utf-8 -*-
"""M160a: the unified category + type taxonomy."""
from __future__ import annotations

from mtkgui.engine.step_types import (
    CATEGORY_ORDER,
    EXTERNAL_GUI_VERDICTS,
    MESSAGE_CLOSE_ACTION,
    STEP_CATEGORIES,
    STEP_TYPE_TO_KIND,
    STEP_TYPES_ALL,
    valid_type,
)


def test_eight_categories_and_thirty_two_sub_types():
    assert len(STEP_CATEGORIES) == 8
    assert CATEGORY_ORDER == tuple(STEP_CATEGORIES)
    assert sum(len(types) for types in STEP_CATEGORIES.values()) == 32
    assert len(STEP_TYPES_ALL) == 32


def test_valid_type_accepts_declared_pairs_and_rejects_unknown():
    for category, sub_type in STEP_TYPES_ALL:
        assert valid_type(category, sub_type), (category, sub_type)
    assert not valid_type("Console", "flash")
    assert not valid_type("ExternalGui", "serial")
    assert not valid_type("NoSuchCategory", "serial")
    assert not valid_type("Message", "")


def test_every_pair_maps_to_a_non_empty_engine_kind():
    assert len(STEP_TYPE_TO_KIND) == 32
    assert set(STEP_TYPE_TO_KIND) == set(STEP_TYPES_ALL)
    assert all(isinstance(kind, str) and kind.strip()
               for kind in STEP_TYPE_TO_KIND.values())


def test_verdict_constants_follow_the_directive():
    assert EXTERNAL_GUI_VERDICTS["flash"]["dialog"] == "MessageGoStop"
    assert EXTERNAL_GUI_VERDICTS["test"]["dialog"] == "MessageYesNo"
    assert all(spec["abort_on_negative"]
               for spec in EXTERNAL_GUI_VERDICTS.values())
    assert MESSAGE_CLOSE_ACTION["ok"] == "pass"
    assert MESSAGE_CLOSE_ACTION["yesno"] == "fail"
    assert MESSAGE_CLOSE_ACTION["gostop"] == "abort"
