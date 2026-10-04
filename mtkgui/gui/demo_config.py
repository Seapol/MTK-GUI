# -*- coding: utf-8 -*-
"""P2-2 visual config demo (headless-safe, rc=0 on success).

Full closed loop offscreen: load real project YAML -> form seed ->
illegal-input interception -> edit + validate -> save (auto snapshot +
formatted YAML) -> reload round-trip -> hot-apply signal -> rollback +
diff.  Exit 0 = all checkpoints passed.
"""
from __future__ import annotations

import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import yaml  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from mtkgui.gui.config_page import ConfigPage  # noqa: E402
from mtkgui.gui.config_spec import (get_path, set_path,  # noqa: E402
                                    validate_config, validate_value,
                                    FIELDS_BY_PATH)
from mtkgui.gui.config_store import ConfigStore  # noqa: E402

BASE_CFG = {
    "project": {"software": "mtk-gui v2.0.0", "revision": "1.0",
                "created": "2026-10-04"},
    "product": {"part_number": "FRDM-IMX93", "core_id": "12345",
                "batch": "Dev"},
    "test_workflow": {"stop_if_failure": False, "stop_if_any_short": True,
                      "retry": 0},
    "equipment": {"host": {"fields": {"OS": "Windows 11 Pro x64",
                                      "Test SW": "mtk-gui v2.0.0"}}},
}


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    tmp = tempfile.mkdtemp(prefix="p2_2_demo_")
    yaml_path = os.path.join(tmp, "project.yaml")
    with open(yaml_path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(BASE_CFG, fh, sort_keys=False, allow_unicode=True)

    # 1. schema-level validation engine
    cfg = ConfigStore.load(yaml_path)
    assert validate_config(cfg) == [], "baseline config must be valid"
    bad = dict(cfg)
    set_path(bad, "test_workflow.retry", -1)
    set_path(bad, "sharepoint.site_url", "not-a-url")
    issues = validate_config(bad)
    assert {i.path for i in issues} == {"test_workflow.retry",
                                        "sharepoint.site_url"}, "illegal catch"
    # firmware image path: existence is strictly enforced (P1-6/7 lineage)
    img = os.path.join(tmp, "fat_firmware.bin")
    open(img, "wb").write(b"\x00\x01")
    assert validate_value(FIELDS_BY_PATH["firmware.fat_image"],
                          img) is None, "real image accepted"
    ghost = validate_value(FIELDS_BY_PATH["firmware.fat_image"],
                           "/no/such/image.bin")
    assert ghost is not None and "does not exist" in ghost.reason

    # 2. store: apply + formatted save + audit, unknown keys preserved
    store = ConfigStore(snapshot_dir=os.path.join(tmp, "snaps"))
    new_cfg, changes = store.apply_and_save(
        cfg, {"test_workflow.retry": "2",
              "sharepoint.site_url": "https://corp.sharepoint.com/ict",
              "sharepoint.enabled": True,
              "sharepoint.upload_retry_count": "3"},
        yaml_path)
    assert get_path(new_cfg, "test_workflow.retry") == 2, "coerce int"
    assert get_path(new_cfg, "sharepoint.enabled") is True, "coerce bool"
    assert get_path(new_cfg, "equipment.host.fields.OS") == \
        "Windows 11 Pro x64", "unregistered key dropped!"
    assert get_path(new_cfg, "project.created") == "2026-10-04", \
        "unknown leaf dropped!"
    assert changes and store.audit, "audit trail empty"

    # 3. GUI page: seed -> real-time validation -> save blocked on illegal
    page = ConfigPage(yaml_path, store=store)
    page.interactive = False  # headless-safe (no modal dialogs)
    retry_edit = page._editors["test_workflow.retry"]
    retry_edit.setText("99")  # > max 9
    issue = page._validate_field(FIELDS_BY_PATH["test_workflow.retry"])
    assert issue is not None and "max" in issue.reason, "real-time validate"
    retry_edit.setText("3")   # back to legal
    assert page._validate_field(
        FIELDS_BY_PATH["test_workflow.retry"]) is None, "recovery"

    applied = []
    page.config_applied.connect(applied.append)  # hot-effect hook

    page._editors["product.part_number"].setText("")  # required -> empty
    assert page.on_save() is None, "illegal save must be intercepted"
    page._editors["product.part_number"].setText("FRDM-IMX93")

    result = page.on_save()
    assert result is not None, "legal save must pass"
    saved_cfg, save_changes = result
    assert get_path(saved_cfg, "test_workflow.retry") == 3, "saved value"
    assert applied and applied[-1] == saved_cfg, "hot-apply signal"
    reloaded = ConfigStore.load(yaml_path)
    assert reloaded == saved_cfg, "save round-trip mismatch"

    # 4. snapshot rollback + diff
    snaps = store.list_snapshots()
    assert len(snaps) >= 2, "snapshots missing (auto pre-save)"
    # deterministic pick: same-second snapshot ids sort ambiguously,
    # so select the pre-save snapshot BY CONTENT (retry still == 2)
    cand = [s for s in snaps
            if (ConfigStore.load(s.path).get("test_workflow")
                or {}).get("retry") == 2]
    assert cand, "pre-save snapshot (retry=2) missing"
    restored, diffs = store.rollback(reloaded, cand[0].snap_id)
    assert get_path(restored, "test_workflow.retry") == 2, "rollback value"
    assert diffs, "rollback diff empty"
    assert len(page.store.diff(reloaded, restored)) == len(diffs), "diff"

    print("[P2-2 config demo] visual YAML config OK — schema validation, "
          "illegal interception, formatted save, hot-apply, snapshot/"
          "rollback/diff, backward-compatible preservation all validated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
