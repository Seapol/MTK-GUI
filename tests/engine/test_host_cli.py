# -*- coding: utf-8 -*-
"""P3-B4 Module C: HostCliRunner unit tests (no real hardware)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

from mtkgui.engine.host_cli import (
    HostCliError,
    HostCliRunner,
    extract_items,
    judge_keywords,
    render_template,
)


# ---------------------------------------------------------------- template
def test_render_template_substitutes_params():
    assert render_template("ping -c {{n}} {{host}}",
                           {"n": 3, "host": "1.2.3.4"}) \
        == "ping -c 3 1.2.3.4"


def test_render_template_unknown_placeholder_raises():
    with pytest.raises(HostCliError):
        render_template("echo {{missing}}", {})


# ---------------------------------------------------------------- judging
def test_judge_positive_keyword():
    assert judge_keywords(["Success: 1"])[0] == "Pass"


def test_judge_negative_wins():
    verdict, reason = judge_keywords(["Success", "Error: bad"])
    assert verdict == "Fail" and "Error" in reason


def test_judge_no_keywords_exit_zero():
    assert judge_keywords(["plain line"], exit_code=0)[0] == "Pass"


def test_judge_no_keywords_nonzero_exit():
    assert judge_keywords(["plain"], exit_code=1)[0] == "Fail"


def test_judge_require_exit_zero_overrides_keywords():
    verdict, reason = judge_keywords(["Success"], require_exit_zero=True,
                                     exit_code=3)
    assert verdict == "Fail" and "3" in reason


# -------------------------------------------------------------- extraction
def test_extract_items_first_match_wins():
    items = extract_items(["Signal / Noise: -41 dBm"],
                          {"rssi": r"Signal / Noise: (-?\d+) dBm"})
    assert items == {"rssi": "-41"}


def test_extract_items_missing_is_absent():
    assert extract_items(["nothing"], {"x": r"(\d+)"}) == {}


# ------------------------------------------------------------- runner real
@pytest.fixture
def runner():
    logs = []
    return HostCliRunner(log_sink=logs.append, station_id="ST01",
                         user="tester"), logs


def test_runner_echo(runner):
    r, logs = runner
    res = r.run('echo "Success {{name}}"', {"name": "x"})
    assert res.verdict == "Pass" and res.exit_code == 0
    assert "Success x" in res.lines
    assert any("[ST01]" in l and "[tester]" in l for l in logs)


def test_runner_negative_exit(runner):
    r, _ = runner
    res = r.run("ls /nonexistent_dir_xyz", require_exit_zero=True)
    assert res.verdict == "Fail" and res.exit_code != 0


def test_runner_missing_command(runner):
    r, _ = runner
    res = r.run("nonexistent_cmd_xyz_123", require_exit_zero=True)
    assert res.verdict == "Fail" and res.exit_code != 0


def test_runner_timeout_kills(runner):
    r, _ = runner
    import time
    t0 = time.monotonic()
    res = r.run("sleep 10", timeout_s=1.5, require_exit_zero=True)
    assert res.verdict == "Fail"
    assert any("timeout" in l for l in res.lines)
    assert time.monotonic() - t0 < 5


def test_runner_stderr_split(runner):
    r, _ = runner
    res = r.run("echo out; echo err 1>&2", require_exit_zero=True)
    assert "out" in res.lines
    assert "[stderr] err" in res.lines


def test_runner_sw_vers_extract(runner):
    """Real macOS command: version extraction must work."""
    r, _ = runner
    res = r.run("sw_vers",
                regex_extracts={"product_version":
                                r"ProductVersion:\s+(\S+)"})
    assert res.exit_code == 0 and res.items.get("product_version")


def test_runner_env_extra(runner):
    r, _ = runner
    res = r.run("printenv MY_TEST_VAR", env_extra={"MY_TEST_VAR": "42"})
    assert "42" in res.lines
