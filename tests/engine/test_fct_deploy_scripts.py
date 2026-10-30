# -*- coding: utf-8 -*-
"""M42: the console deploy_scripts switch is RETIRED.

Asset transfer is owned by the per-step SFTP Put / Pull rows (M41);
the console section keeps the SFTP path fields only.  A legacy YAML
that still carries ``deploy_scripts`` loads cleanly (the key is
ignored, never re-emitted).
"""

from mtkgui.engine.fct_test_config import (
    ConsoleCfg,
    FctTestConfig,
)
from mtkgui.engine.fct_test_runner import FctTestRunner


def _linux_cfg(**console_kw):
    kw = dict(port="/dev/ttyDUT", ssh_host="192.168.10.10",
              scripts_local_dir="dut_scripts/linux",
              scripts_remote_dir="/root")
    kw.update(console_kw)
    return FctTestConfig(dut_type="linux", console=ConsoleCfg(**kw))


# ------------------------------------------------------------- model IO
def test_deploy_switch_is_gone():
    assert not hasattr(ConsoleCfg(), "deploy_scripts")
    node = _linux_cfg().to_dict()["console"]
    assert "deploy_scripts" not in node


def test_sftp_path_fields_round_trip():
    cfg = _linux_cfg(pull_remote_dir="/tmp/results",
                     pull_local_dir="results")
    node = cfg.to_dict()["console"]
    assert node["scripts_local_dir"] == "dut_scripts/linux"
    assert node["scripts_remote_dir"] == "/root"
    assert node["pull_remote_dir"] == "/tmp/results"
    assert node["pull_local_dir"] == "results"
    restored = FctTestConfig.from_dict(
        {"console": node, "dut_type": "linux"}).console
    assert restored.scripts_local_dir == "dut_scripts/linux"
    assert restored.scripts_remote_dir == "/root"
    assert restored.pull_remote_dir == "/tmp/results"
    assert restored.pull_local_dir == "results"


def test_legacy_yaml_deploy_key_is_ignored():
    """A project saved with the retired switch still loads: the key is
    dropped and nothing is re-emitted."""
    legacy = {
        "dut_type": "linux",
        "console": {"port": "/dev/ttyDUT", "ssh_host": "192.168.10.10",
                    "deploy_scripts": True,
                    "scripts_local_dir": "assets",
                    "scripts_remote_dir": "/root"},
    }
    cfg = FctTestConfig.from_dict(legacy)
    assert cfg.console.scripts_local_dir == "assets"
    assert "deploy_scripts" not in cfg.to_dict()["console"]


# ------------------------------------------------------------- validation
def test_validate_linux_console_clean():
    assert _linux_cfg().validate() == []


def test_empty_sftp_paths_are_not_an_error():
    """M42: no deploy switch -> no scripts_local_dir requirement."""
    assert _linux_cfg(scripts_local_dir="").validate() == []


def test_bare_metal_does_not_complain_about_deploy():
    cfg = FctTestConfig(console=ConsoleCfg(port="/dev/ttyDUT",
                                           scripts_local_dir="assets"),
                        dut_type="bare_metal")
    assert cfg.validate() == []


# ------------------------------------------------------------- runner
def test_runner_has_no_deploy_step():
    """The cycle no longer provisions scripts before the console rows."""
    assert not hasattr(FctTestRunner, "deploy_scripts")
