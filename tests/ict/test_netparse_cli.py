# -*- coding: utf-8 -*-
"""``python -m mtkgui.ict.netparse`` CLI contract tests."""
from __future__ import annotations

import json

from mtkgui.ict.netparse.cli import main

NET = """*SIGNAL* 3V3
U1.5 TP1.1
*SIGNAL* GND
J1.2 U1.1
"""

ALLEGRO_REPORT = """Allegro Report
C:/work/board.brd

Net Name,Net Pins
3V3,TP1.1 U1.5
SIG_A,U1.2
"""


def _report_file(tmp_path):
    path = tmp_path / "report.net"
    path.write_text(ALLEGRO_REPORT, encoding="utf-8")
    return str(path)


def _net_file(tmp_path):
    path = tmp_path / "board.net"
    path.write_text(NET, encoding="utf-8")
    return str(path)


def test_cli_json_stdout(tmp_path, capsys):
    code = main([_net_file(tmp_path)])
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert code == 0
    assert payload["schema"] == "mtkgui.ict.netparse.v1"
    assert payload["total"] == 2
    assert payload["nets"]["power"][0]["test_point"] == "TP1.1"


def test_cli_csv_stdout(tmp_path, capsys):
    code = main([_net_file(tmp_path), "--format", "csv"])
    out = capsys.readouterr().out
    assert code == 0
    assert out.splitlines()[0].startswith("net,category,test_point")


def test_cli_output_file(tmp_path, capsys):
    out_file = tmp_path / "nets.json"
    code = main([_net_file(tmp_path), "--output", str(out_file)])
    assert code == 0
    assert capsys.readouterr().out == ""
    payload = json.loads(out_file.read_text(encoding="utf-8"))
    assert payload["total"] == 2


def test_cli_missing_input_returns_2(tmp_path, capsys):
    code = main([str(tmp_path / "nope.net")])
    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    assert captured.err.startswith("error:")


def test_cli_bad_rules_returns_2(tmp_path, capsys):
    rules = tmp_path / "rules.json"
    rules.write_text("[1, 2]", encoding="utf-8")
    code = main([_net_file(tmp_path), "--rules", str(rules)])
    captured = capsys.readouterr()
    assert code == 2
    assert "rules JSON must be an object" in captured.err


def test_cli_auto_detects_allegro_report(tmp_path, capsys):
    code = main([_report_file(tmp_path)])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["format"] == "allegro_report"
    assert payload["total"] == 2
    assert payload["nets"]["power"][0]["net"] == "3V3"


def test_cli_applies_user_rules(tmp_path, capsys):
    rules = tmp_path / "rules.json"
    rules.write_text(json.dumps({"exclude": "^SIG_"}), encoding="utf-8")
    code = main([_report_file(tmp_path), "--rules", str(rules)])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    filtered = {row["net"]: row["reason"] for row in payload["filtered"]}
    assert "SIG_A" in filtered
    assert "Exclude Parse Nets" in filtered["SIG_A"]


def test_cli_compact_indent_zero(tmp_path, capsys):
    code = main([_net_file(tmp_path), "--indent", "0"])
    out = capsys.readouterr().out
    assert code == 0
    assert len(out.strip().splitlines()) == 1       # compact single line
    assert json.loads(out)["total"] == 2


def test_cli_missing_rules_file_returns_2(tmp_path, capsys):
    code = main([_net_file(tmp_path), "--rules",
                 str(tmp_path / "missing.json")])
    captured = capsys.readouterr()
    assert code == 2
    assert "cannot read rules file" in captured.err


def test_cli_unwritable_output_returns_2(tmp_path, capsys):
    target = tmp_path / "no-such-dir" / "nets.json"
    code = main([_net_file(tmp_path), "--output", str(target)])
    captured = capsys.readouterr()
    assert code == 2
    assert "cannot write output" in captured.err
