# -*- coding: utf-8 -*-
"""M3: frozen base rule library + external learnable rule layers.

Covers PART 2 of the M3 spec: ``--export-base`` snapshot, external
merge semantics (add / remove / reweight / entries) with full
``applied_rules`` auditability, the synthetic new-project learn loop
(base-only low confidence -> external rules applied -> confidence
rises -> ``tokens.remove`` effect demonstrated), ``--suggest``
candidates, the 1.4 regression gate and M2 backward compatibility.
"""
from __future__ import annotations

import json

import pytest

from mtkgui.ict.netparse import (parse_testable_nets, result_to_dict,
                                 RULES_VERSION)
from mtkgui.ict.netparse.rule_layers import (BASE_SCHEMA, RULES_SCHEMA,
                                             export_base_rules,
                                             load_external,
                                             regression_gate, suggest)

FIXTURE = ("Allegro Report\nC:/work/x.brd\n\nNet Name,Net Pins\n"
           "BB_MLB_CLK,U1.1 TP1.1\n"
           "TELEM_PWR_MON,U1.2 TP2.1\n"
           "NAV_SER_VO,U1.3 TP3.1\n")

EXTERNAL = {
    "schema": RULES_SCHEMA, "version": "1.0", "applies_to": ["all"],
    "tokens": {"add": {"power": ["TELEM"]},
               "remove": {"interface": ["MLB"]}},
    "entries": [{"id": "r1", "pattern": "^NAV_SER_VO$",
                 "class": "control_io", "sub_class": "",
                 "reason": "servo actuator enable",
                 "source": "synthetic", "date": "2026-10-22",
                 "version": "1.0"}],
}


def _names(result, bucket):
    return [r.name for r in getattr(result, bucket)]


# ------------------------------------------------------------- 1.1 base
def test_rules_version_exported_in_json():
    payload = result_to_dict(parse_testable_nets(FIXTURE))
    assert payload["rules_version"] == RULES_VERSION == "2.0"


def test_export_base_snapshot_schema(tmp_path):
    snapshot = export_base_rules()
    assert snapshot["schema"] == BASE_SCHEMA
    assert snapshot["rules_version"] == "2.0"
    assert "MLB" in snapshot["tokens"]["interface"]
    assert "CLK" in snapshot["tokens"]["clock"]
    assert "RESET" in " ".join(snapshot["tokens"]["control_io"])
    assert snapshot["device_roles"]["clock_gen"]
    path = tmp_path / "base_rules.json"
    path.write_text(json.dumps(snapshot), encoding="utf-8")
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["schema"] == BASE_SCHEMA


# --------------------------------------------------- 1.2 external merge
def test_load_external_merge_order(tmp_path):
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    a.write_text(json.dumps({
        "schema": RULES_SCHEMA,
        "tokens": {"add": {"power": ["TELEM"]},
                   "reweight": {"clock": {"CLK": "high"}}},
        "entries": [{"id": "r1", "pattern": "^X$",
                     "class": "clock"}]}), encoding="utf-8")
    b.write_text(json.dumps({
        "schema": RULES_SCHEMA,
        "tokens": {"add": {"power": ["CHASSIS"]},
                   "reweight": {"clock": {"CLK": "low"}}},
        "entries": [{"id": "r2", "pattern": "^Y$",
                     "class": "power"}]}), encoding="utf-8")
    merged = load_external([str(a), str(b)])
    assert merged["tokens"]["add"]["power"] == ["TELEM", "CHASSIS"]
    # later file overrides the same reweight key
    assert merged["tokens"]["reweight"]["clock"]["CLK"] == "low"
    assert [e["id"] for e in merged["entries"]] == ["r1", "r2"]


def test_load_external_rejects_bad_schema_and_weight(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema": "other.v9"}),
                   encoding="utf-8")
    with pytest.raises(ValueError):
        load_external([str(bad)])
    heavy = tmp_path / "heavy.json"
    heavy.write_text(json.dumps({
        "schema": RULES_SCHEMA,
        "tokens": {"reweight": {"clock": {"CLK": "ultra"}}}}),
        encoding="utf-8")
    with pytest.raises(ValueError):
        load_external([str(heavy)])


def test_no_external_rules_identical_to_m2():
    base = parse_testable_nets(FIXTURE)
    assert base.applied_rules == []
    # foreign-style nets: none classified by the frozen base
    assert base.power == [] and base.clock == [] \
        and base.control_io == []
    assert all(r.sub_class == "unclassified" for r in base.others)


# --------------------------------------------- 1.2 external application
def test_external_entries_tokens_and_audit():
    result = parse_testable_nets(FIXTURE, external=EXTERNAL)
    by_name = {r.name: r for r in
               result.power + result.clock + result.control_io
               + result.others}
    # entry r1: NAV_SER_VO -> control_io, auditable provenance
    assert "NAV_SER_VO" in _names(result, "control_io")
    assert by_name["NAV_SER_VO"].provenance == "external:r1"
    # token add: TELEM -> power
    assert "TELEM_PWR_MON" in _names(result, "power")
    assert by_name["TELEM_PWR_MON"].provenance == "external:token:TELEM"
    # token remove: MLB no longer interface -> BB_MLB_CLK is a clock
    assert "BB_MLB_CLK" in _names(result, "clock")
    # full audit trail
    kinds = {a["kind"] for a in result.applied_rules}
    assert kinds == {"entry", "tokens.add", "tokens.remove"}
    audit = {(a["kind"], a.get("value")) for a in result.applied_rules}
    assert ("entry", "^NAV_SER_VO$") in audit
    assert ("tokens.add", "TELEM") in audit
    assert ("tokens.remove", "MLB") in audit
    payload = result_to_dict(result)
    assert payload["applied_rules"] == result.applied_rules


def test_token_remove_restores_base_after_run():
    """The layer patch must not leak into later no-rules runs."""
    parse_testable_nets(FIXTURE, external=EXTERNAL)
    after = parse_testable_nets(FIXTURE)
    assert all(r.sub_class == "unclassified" for r in after.others)
    assert after.power == [] and after.clock == []


def test_reweight_overrides_confidence():
    ext = {"schema": RULES_SCHEMA,
           "tokens": {"reweight": {"clock": {"CLK": "high"}}}}
    result = parse_testable_nets(
        "Net Name,Net Pins\nDUT_CLK,U1.1 TP1.1\n", external=ext)
    rec = result.clock[0]
    assert rec.confidence == "high"
    assert any(a["kind"] == "reweight" for a in result.applied_rules)


def test_device_role_add_and_clock_freq_add():
    from mtkgui.ict.netparse.confidence import clock_freq_hz
    from mtkgui.ict.netparse.rule_layers import layer_context
    library = {"U9": {"part_number": "XYZ-PLL-9", "description": ""}}
    ext = {"schema": RULES_SCHEMA,
           "device_roles": {"add": {"XYZ-PLL-9": "clock_gen"}},
           "clock_nominal_freq": {"add": {"NAVREF": 32768}}}
    # the nominal-frequency addition is a per-run layer patch
    with layer_context(ext):
        assert clock_freq_hz("NAVREF_CLK") == 32768.0
    assert clock_freq_hz("NAVREF_CLK") == 0.0   # restored after the run
    result = parse_testable_nets(
        "Net Name,Net Pins\nNAVREF_CLK,U9.1 TP1.1\n",
        library=library, external=ext)
    # clock_gen role via the ADDED part-number marker: output -> clock
    assert len(result.clock) == 1
    assert result.clock[0].provenance == "device_role:clock_gen"


def test_external_beats_exclude_regex():
    ext = {"schema": RULES_SCHEMA,
           "entries": [{"id": "r9", "pattern": "^WIFI_EN$",
                        "class": "control_io", "sub_class": ""}]}
    result = parse_testable_nets(
        "Net Name,Net Pins\nWIFI_EN,U1.1 TP1.1\n", external=ext)
    assert _names(result, "control_io") == ["WIFI_EN"]


# --------------------------------------------------------- 1.3 suggest
def test_suggest_extracts_candidates():
    result = parse_testable_nets(FIXTURE)
    candidates = suggest(result, library={"U1": {"part_number":
                                                 "ZZZ-UNK-1",
                                                 "description": ""}})
    assert candidates, "base-only foreign nets must yield candidates"
    actions = " ".join(c["suggested_action"] for c in candidates)
    assert "tokens.add" in actions or "entry ^" in actions
    for cand in candidates:
        assert set(cand) >= {"candidate", "suggested_action", "class",
                             "reason", "evidence"}
    # repeated unknown member part number -> device-role suggestion
    roles = [c for c in candidates if c["class"] == "device_roles"]
    assert any("ZZZ-UNK-1" in c["suggested_action"] for c in roles)


# ------------------------------------------------------ 1.4 gate
def test_regression_gate():
    base = {"p": {"overall": 0.60, "legacy": 0.50, "amb": 2}}
    ok, violations = regression_gate(
        base, {"p": {"overall": 0.65, "legacy": 0.50, "amb": 2}})
    assert ok and violations == []
    ok, violations = regression_gate(
        base, {"p": {"overall": 0.55, "legacy": 0.50, "amb": 3}})
    assert not ok
    assert len(violations) == 2


# ------------------------------------- CLI: real learn-loop integration
def _run_cli(argv):
    from mtkgui.ict.netparse.cli import main
    return main(argv)


def test_cli_export_base(tmp_path, capsys):
    out = tmp_path / "base_rules.json"
    assert _run_cli(["--export-base", str(out)]) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["schema"] == BASE_SCHEMA
    assert "snapshot written" in capsys.readouterr().out


def test_cli_learn_loop_rises_confidence(tmp_path):
    fixture = tmp_path / "m3_foreign.net"
    fixture.write_text(FIXTURE, encoding="utf-8")
    ext_file = tmp_path / "learned.json"
    ext_file.write_text(json.dumps(EXTERNAL), encoding="utf-8")

    def _summary(argv):
        from mtkgui.ict.netparse.cli import main
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            assert main(argv) == 0
        return json.loads(buf.getvalue())

    base = _summary([str(fixture), "--format", "json"])
    learned = _summary([str(fixture), "--rules", str(ext_file),
                        "--format", "json"])
    assert base["summary"]["overall_confidence"] == 0.0
    assert (learned["summary"]["overall_confidence"]
            > base["summary"]["overall_confidence"])
    ids = {a["id"] for a in learned["applied_rules"]}
    assert {"r1", "token:TELEM", "remove:MLB"} <= ids


def test_cli_suggest_flag(tmp_path, capsys):
    fixture = tmp_path / "m3_foreign.net"
    fixture.write_text(FIXTURE, encoding="utf-8")
    assert _run_cli([str(fixture), "--suggest"]) == 0
    candidates = json.loads(capsys.readouterr().out)
    assert candidates and "suggested_action" in candidates[0]
