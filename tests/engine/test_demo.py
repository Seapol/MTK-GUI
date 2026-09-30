# -*- coding: utf-8 -*-
"""Headless demo (python -m mtkgui.engine.demo): full sequence without
a GUI, mocked driver responses, CSV waveform log, stop-on-fail."""
from __future__ import annotations

import sys

import yaml

from mtkgui.engine import demo as demo_mod
from mtkgui.engine.demo import HeadlessEnv, main


def write_config(tmp_path, config: dict) -> str:
    path = tmp_path / "demo_project.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False),
                    encoding="utf-8")
    return str(path)


def run_demo_main(tmp_path, monkeypatch, mode="virtual", inject="",
                  stop_on_fail=True, extra_args=None, config_overrides=None):
    """Run demo.main() in-process on a temp config; returns (rc, logs)."""
    from tests.engine.conftest import make_config

    cfg = make_config()
    if config_overrides:
        for section, values in config_overrides.items():
            cfg.setdefault(section, {}).update(values)
    cfg_path = write_config(tmp_path, cfg)
    logs = tmp_path / "logs"
    argv = ["demo", "--config", cfg_path, "--logs-dir", str(logs),
            "--mode", mode]
    if inject:
        argv += ["--inject", inject]
    if not stop_on_fail:
        argv += ["--no-stop-on-fail"]
    argv += list(extra_args or [])
    rc = main(argv[1:])
    return rc, logs


class TestVirtualMode:
    def test_full_sequence_passes(self, tmp_path, monkeypatch, capsys):
        rc, logs = run_demo_main(tmp_path, monkeypatch)
        assert rc == 0
        out = capsys.readouterr().out
        assert "TEST SEQUENCE REPORT" in out
        # production sequence stages present
        for stage in ("ICT", "Flash FAT Firmware", "FCT",
                      "Flash OOBE Firmware"):
            assert f"Stage: " in out or stage in out
        # waveform CSV written to the requested logs dir
        csvs = list(logs.glob("power_rails*.csv"))
        assert csvs, "power rail CSV log missing"

    def test_fault_injection_stops_the_run(self, tmp_path, monkeypatch,
                                           capsys):
        rc, _logs = run_demo_main(tmp_path, monkeypatch, inject="fail=100")
        assert rc == 1
        out = capsys.readouterr().out
        assert "Overall Result : FAIL" in out
        assert "abort" in out.lower()

    def test_no_stop_on_fail_runs_everything(self, tmp_path,
                                             monkeypatch, capsys):
        rc, _logs = run_demo_main(tmp_path, monkeypatch, inject="fail=100",
                                  stop_on_fail=False)
        assert rc == 1
        out = capsys.readouterr().out
        assert "Overall Result : FAIL" in out
        assert "Stage 4" in out   # OOBE flash stage still reached


class TestRealMode:
    def test_scripted_drivers_full_pass(self, tmp_path, monkeypatch,
                                        capsys):
        monkeypatch.delitem(sys.modules, "mtkgui.drivers", raising=False)
        rc, _logs = run_demo_main(tmp_path, monkeypatch, mode="real")
        assert rc == 0
        out = capsys.readouterr().out
        assert "Overall Result : PASS" in out
        assert "(mode: real" in out


class TestDemoEnv:
    def test_headless_env_implements_runner_bridge(self, tmp_path):
        from tests.engine.conftest import make_env

        env, stages = make_env(tmp_path=tmp_path)
        assert [s.name for s in stages][0] == "ICT"
        steps = env._steps_template(len(env.ict_steps),
                                    env._fct_row_count())
        assert steps[0][0] == "ict"
        assert ("stage", 0) in steps
        assert ("fctconn",) in steps          # console connect pre-FCT
        assert steps[-1][0] == "stage"

    def test_write_csv_uses_logs_dir(self, tmp_path):
        from tests.engine.conftest import make_env

        env, _stages = make_env(tmp_path=tmp_path)
        path = env._write_csv([[0.0, 1.0]], None)
        assert path.parent == tmp_path
        assert "_virtual" in path.name

    def test_operator_stop_reporting(self, tmp_path):
        from mtkgui.engine.runner import TestRunner
        from tests.engine.conftest import make_env

        env, _stages = make_env(tmp_path=tmp_path)
        runner = TestRunner(env)
        env.runner = runner
        runner.start(1)
        runner.abort()
        assert runner.state == "idle"


class TestRetryFromYaml:
    """The authoritative YAML key is test_workflow.retry (spec): the
    demo honors it, and the --retry CLI flag takes precedence."""

    def test_yaml_retry_is_honored(self, tmp_path, monkeypatch, capsys):
        rc, _ = run_demo_main(
            tmp_path, monkeypatch,
            config_overrides={"test_workflow": {"retry": 2}})
        assert rc == 0
        assert "Step retry: 2 attempt(s)" in capsys.readouterr().out

    def test_cli_retry_overrides_yaml(self, tmp_path, monkeypatch, capsys):
        rc, _ = run_demo_main(
            tmp_path, monkeypatch, extra_args=["--retry", "1"],
            config_overrides={"test_workflow": {"retry": 3}})
        assert rc == 0
        assert "Step retry: 1 attempt(s)" in capsys.readouterr().out

    def test_no_retry_key_is_off(self, tmp_path, monkeypatch, capsys):
        rc, _ = run_demo_main(tmp_path, monkeypatch)
        assert rc == 0
        assert "Step retry" not in capsys.readouterr().out
