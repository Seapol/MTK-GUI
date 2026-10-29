# -*- coding: utf-8 -*-
"""P3-B7 task A: Linux DUT script-asset provisioning over SFTP.

Covers the ConsoleCfg deploy fields (YAML round-trip + validation) and
FctTestRunner.deploy_scripts (whole-folder put_dir, flat put_file
fallback, missing SFTP capability / missing folder -> FAIL and stop).
"""

import os

from mtkgui.engine.fct_test_config import (
    ConsoleCfg,
    FctTestConfig,
)
from mtkgui.engine.fct_test_runner import FctTestRunner


def _linux_cfg(**console_kw):
    kw = dict(port="/dev/ttyDUT", ssh_host="192.168.10.10",
              deploy_scripts=True, scripts_local_dir="dut_scripts/linux",
              scripts_remote_dir="/root")
    kw.update(console_kw)
    return FctTestConfig(dut_type="linux", console=ConsoleCfg(**kw))


# ------------------------------------------------------------- model IO
def test_deploy_fields_round_trip():
    cfg = _linux_cfg()
    node = cfg.to_dict()["console"]
    assert node["deploy_scripts"] is True
    assert node["scripts_local_dir"] == "dut_scripts/linux"
    assert node["scripts_remote_dir"] == "/root"
    restored = FctTestConfig.from_dict(
        {"console": node, "dut_type": "linux"}).console
    assert restored.deploy_scripts is True
    assert restored.scripts_local_dir == "dut_scripts/linux"
    assert restored.scripts_remote_dir == "/root"


def test_validate_linux_deploy_clean():
    assert _linux_cfg().validate() == []


def test_validate_deploy_requires_local_dir():
    errs = _linux_cfg(scripts_local_dir="").validate()
    assert any("scripts_local_dir" in e for e in errs)


def test_validate_deploy_requires_ssh_host():
    errs = _linux_cfg(ssh_host="").validate()
    assert any("ssh_host" in e for e in errs)


def test_validate_bare_metal_rejects_deploy():
    cfg = FctTestConfig(
        dut_type="bare_metal",
        console=ConsoleCfg(port="/dev/ttyDUT",
                           deploy_scripts=True,
                           scripts_local_dir="dut_scripts/linux"))
    errs = cfg.validate()
    assert any("SFTP" in e and "Linux" in e for e in errs)


# ------------------------------------------------------------- runner
class _PutDirChannel:
    def __init__(self):
        self.seen = None

    def put_dir(self, local, remote=""):
        out = []
        for root, _d, files in os.walk(local):
            for f in files:
                out.append((os.path.join(root, f), f"{remote}/{f}", 1))
        self.seen = (local, remote, out)
        return out


class _PutFileChannel:
    def __init__(self):
        self.puts = []

    def put_file(self, local, remote=""):
        self.puts.append((local, remote))


class _NoSftpChannel:
    pass


def _asset_folder(tmp_path):
    d = tmp_path / "dut_scripts" / "linux"
    d.mkdir(parents=True)
    (d / "load_rf_drivers.sh").write_text("#!/bin/sh\necho ok\n")
    (d / "connect_wifi.sh").write_text("#!/bin/sh\necho wifi\n")
    return d


def test_deploy_off_returns_none(tmp_path):
    cfg = _linux_cfg(deploy_scripts=False)
    runner = FctTestRunner(cfg)
    assert runner.deploy_scripts(_NoSftpChannel()) is None


def test_deploy_put_dir_uses_remote(tmp_path):
    d = _asset_folder(tmp_path)
    cfg = _linux_cfg(scripts_local_dir=str(d))
    ch = _PutDirChannel()
    res = FctTestRunner(cfg).deploy_scripts(ch)
    assert res.verdict == "PASS" and res.name == "Deploy DUT scripts"
    assert "2 file" in res.detail and "/root" in res.detail
    assert ch.seen[1] == "/root" and len(ch.seen[2]) == 2


def test_deploy_relative_dir_uses_base(tmp_path):
    _asset_folder(tmp_path)
    cfg = _linux_cfg(scripts_local_dir="dut_scripts/linux")
    ch = _PutDirChannel()
    runner = FctTestRunner(cfg, scripts_base_dir=str(tmp_path))
    res = runner.deploy_scripts(ch)
    assert res.verdict == "PASS"
    assert ch.seen[0] == str(tmp_path / "dut_scripts" / "linux")


def test_deploy_flat_put_file_fallback(tmp_path):
    d = _asset_folder(tmp_path)
    cfg = _linux_cfg(scripts_local_dir=str(d))
    ch = _PutFileChannel()
    res = FctTestRunner(cfg).deploy_scripts(ch)
    assert res.verdict == "PASS"
    assert len(ch.puts) == 2
    assert all(rp.startswith("/root/") for _lp, rp in ch.puts)


def test_deploy_no_sftp_capability_fails(tmp_path):
    d = _asset_folder(tmp_path)
    cfg = _linux_cfg(scripts_local_dir=str(d))
    res = FctTestRunner(cfg).deploy_scripts(_NoSftpChannel())
    assert res.verdict == "FAIL" and "SFTP" in res.detail


def test_deploy_missing_folder_fails(tmp_path):
    cfg = _linux_cfg(scripts_local_dir=str(tmp_path / "nope"))
    res = FctTestRunner(cfg).deploy_scripts(_PutDirChannel())
    assert res.verdict == "FAIL"


def test_run_stops_when_deploy_fails(tmp_path):
    # deploy FAIL must abort before any console/RF step runs
    cfg = _linux_cfg(scripts_local_dir=str(tmp_path / "missing"))
    out = FctTestRunner(cfg).run(_NoSftpChannel(), host_runner=None)
    assert out["overall"] == "FAIL"
    assert len(out["results"]) == 1
    assert out["results"][0].name == "Deploy DUT scripts"
