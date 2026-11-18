# -*- coding: utf-8 -*-
"""v2-5: node 03 Firmware Config — stage, slots, YAML shape, refusal.

Qt-free: covers the data module (``firmware_config.py``), the stage
registration and the model YAML round-trip.  The panel itself is
covered by the Qt smoke in ``test_v2_shell_qt.py``.
"""
from __future__ import annotations

from mtkgui.gui.yamlbuild import firmware_config as fc
from mtkgui.gui.yamlbuild import steps_v2 as sv
from mtkgui.gui.yamlbuild.firmware_panel import NO_SLOT_FOOTER
from mtkgui.gui.yamlbuild.model import YamlBuildModel


# ------------------------------------------------------------- stage order
def test_firmware_stage_registered():
    # node 03 sits between Parse nets (02) and Equipment (04) in the v2
    # seven-step wizard, and it is a real panel now, not a placeholder
    assert sv.STEP_KEYS.index("firmware") == sv.STEP_KEYS.index("parse_ict") + 1
    assert sv.STEP_KEYS.index("firmware") == sv.STEP_KEYS.index("equipment") - 1
    assert "firmware" not in sv.PLACEHOLDER_STEPS
    assert sv.STEP_BY_KEY["firmware"].kind == "panel"


# ------------------------------------------------------------- no timeout
def _walk_keys(node, path=""):
    keys = []
    if isinstance(node, dict):
        for key, value in node.items():
            keys.append(f"{path}.{key}")
            keys.extend(_walk_keys(value, f"{path}.{key}"))
    elif isinstance(node, list):
        for i, value in enumerate(node):
            keys.extend(_walk_keys(value, f"{path}[{i}]"))
    return keys


def test_firmware_no_timeout_field():
    # the data module and the emitted YAML never carry a timeout key
    assert not any(k.endswith("timeout") for k in _walk_keys(fc.default_firmware()))
    assert not any(k.endswith("timeout")
                   for k in _walk_keys(fc.emit_firmware(fc.default_firmware())))


# ------------------------------------------------------------- slots legal
def test_firmware_both_slots_disabled_is_legal():
    config = fc.default_firmware()
    config["fat"]["enabled"] = False
    config["oobe"]["enabled"] = False
    out = fc.emit_firmware(config)
    assert out == {"fat": {"enabled": False}, "oobe": {"enabled": False}}
    # the panel footer tells the operator the run flashes nothing
    assert "no firmware slot enabled" in NO_SLOT_FOOTER


def test_firmware_cli_and_gui_independent():
    config = fc.default_firmware()
    config["fat"]["method"] = "cli"
    config["fat"]["cli"]["command"] = "fat_flash.bat --port COM4"
    config["fat"]["cli"]["pass_keywords"] = ["FAT_FLASH_OK"]
    config["oobe"]["enabled"] = True
    config["oobe"]["method"] = "gui"
    config["oobe"]["gui"]["tool_path"] = r"C:\Tools\OobeFlasher.exe"
    out = fc.emit_firmware(config)
    assert out["fat"]["method"] == "cli"
    assert out["fat"]["cli"]["command"] == "fat_flash.bat --port COM4"
    assert out["fat"]["cli"]["pass_keywords"] == ["FAT_FLASH_OK"]
    assert out["oobe"]["method"] == "gui"
    assert out["oobe"]["gui"]["tool_path"] == r"C:\Tools\OobeFlasher.exe"


# ------------------------------------------------------------- legacy refusal
def test_firmware_legacy_keys_refused():
    config, errors = fc.parse_firmware({"fat_image": "fat.bin"})
    assert errors
    assert any("legacy firmware key 'fat_image'" in e for e in errors)
    config, errors = fc.parse_firmware({"oobe_image": "oobe.bin"})
    assert any("legacy firmware key 'oobe_image'" in e for e in errors)


# ------------------------------------------------------------- model round trip
def test_firmware_model_yaml_round_trip():
    model = YamlBuildModel()
    config = fc.default_firmware()
    config["fat"]["cli"]["command"] = "fat_flash.bat --image fat.bin"
    config["oobe"]["enabled"] = True
    config["oobe"]["method"] = "gui"
    config["oobe"]["gui"]["tool_path"] = r"C:\Tools\Flasher.exe"
    model.set_firmware_config(config)
    section = model.to_effective_dict()["yaml_build"]
    assert section["firmware"]["fat"]["cli"]["command"] == \
        "fat_flash.bat --image fat.bin"
    assert section["firmware"]["oobe"]["gui"]["tool_path"] == \
        r"C:\Tools\Flasher.exe"
    # a fresh model applies the emitted firmware section back identically
    loaded = YamlBuildModel()
    errors = loaded.apply_yaml_dict(
        {"yaml_build": {"firmware": section["firmware"]}})
    assert errors == []
    assert loaded.get_firmware_config()["fat"]["cli"]["command"] == \
        "fat_flash.bat --image fat.bin"
    assert loaded.get_firmware_config()["oobe"]["method"] == "gui"


def test_firmware_legacy_key_refused_by_model_load():
    model = YamlBuildModel()
    errors = model.apply_yaml_dict({
        "yaml_build": {"firmware": {"fat_image": "fat.bin"}},
    })
    assert any("legacy firmware key 'fat_image'" in e for e in errors)
