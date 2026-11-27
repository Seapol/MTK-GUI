# -*- coding: utf-8 -*-
"""step_types — M160 unified test-step taxonomy (category + type).

One two-level vocabulary shared by ICT and FCT:

* 8 categories, 32 sub-types (``STEP_CATEGORIES``);
* ``valid_type`` / ``CATEGORY_ORDER`` for the editors and validators;
* ``STEP_TYPE_TO_KIND`` — the published-case kind the existing engine
  already understands for every (category, type) pair (Commit A keeps
  the executor untouched; only the display / step model changes);
* verdict semantics: the ExternalGui dialogs and the hard-coded
  close-window (X) fallback of the six Message types.

Pure data: no Qt, no imports from the step model (``fct_build``).
"""
from __future__ import annotations

CATEGORY_MEASUREMENT = "Measurement"
CATEGORY_OPERATION = "Operation"
CATEGORY_CONSOLE = "Console"
CATEGORY_MESSAGE = "Message"
CATEGORY_TRANSFER = "Transfer"
CATEGORY_EXTERNAL_GUI = "ExternalGui"
CATEGORY_WIFI = "Wifi"
CATEGORY_BLUETOOTH = "Bluetooth"

STEP_CATEGORIES = {
    CATEGORY_MEASUREMENT: ("r_gnd", "voltage", "clock"),
    CATEGORY_OPERATION: ("init_instruments", "reset_instruments",
                         "fixture_ready", "power_on", "power_off",
                         "daq_ai_start", "daq_ai_end", "delay"),
    CATEGORY_CONSOLE: ("serial", "ssh", "cli"),
    CATEGORY_MESSAGE: ("ok", "yesno", "gostop",
                       "ok_console", "yesno_console", "gostop_console"),
    CATEGORY_TRANSFER: ("sftp_put", "sftp_get", "serial_put", "serial_pull"),
    CATEGORY_EXTERNAL_GUI: ("flash", "test"),
    CATEGORY_WIFI: ("scan", "ping", "iperf"),
    CATEGORY_BLUETOOTH: ("rssi", "pair", "tone"),
}

#: the 8 categories in display order
CATEGORY_ORDER = tuple(STEP_CATEGORIES)

#: every declared (category, type) pair, in display order
STEP_TYPES_ALL = tuple(
    (category, sub_type)
    for category in CATEGORY_ORDER
    for sub_type in STEP_CATEGORIES[category])

#: (category, type) pairs that belong to ICT only and must never appear
#: in the FCT sequence builder (node 06).  Measurement is the ICT numeric
#: block; the four Operation sub-types drive the fixture / DAQ, not the
#: DUT, so they are out of scope for an FCT flow too.
FCT_EXCLUDED_TYPES = frozenset({
    (CATEGORY_MEASUREMENT, "r_gnd"),
    (CATEGORY_MEASUREMENT, "voltage"),
    (CATEGORY_MEASUREMENT, "clock"),
    (CATEGORY_OPERATION, "init_instruments"),
    (CATEGORY_OPERATION, "fixture_ready"),
    (CATEGORY_OPERATION, "daq_ai_start"),
    (CATEGORY_OPERATION, "daq_ai_end"),
})

#: the 7 FCT categories in display order (Measurement excluded)
FCT_CATEGORY_ORDER = tuple(
    category for category in CATEGORY_ORDER
    if category != CATEGORY_MEASUREMENT)

#: FCT-only category -> sub-types (7 categories, 25 sub-types)
FCT_STEP_CATEGORIES = {
    category: tuple(
        sub_type for sub_type in STEP_CATEGORIES[category]
        if (category, sub_type) not in FCT_EXCLUDED_TYPES)
    for category in FCT_CATEGORY_ORDER
}


def valid_type(category: str, sub_type: str) -> bool:
    """True when ``(category, sub_type)`` is one declared pair."""
    return str(sub_type) in STEP_CATEGORIES.get(str(category), ())


#: (category, type) -> the published fct_test_cases kind the existing
#: executor understands.  Values are the real kind strings already in
#: use (``STEP_TYPE_LABELS`` / the six Message kinds / the legacy FCT
#: method names ``op`` / ``test`` / ``SerialPush`` / ``SerialPull``).
STEP_TYPE_TO_KIND = {
    (CATEGORY_MEASUREMENT, "r_gnd"): "test",
    (CATEGORY_MEASUREMENT, "voltage"): "test",
    (CATEGORY_MEASUREMENT, "clock"): "test",

    (CATEGORY_OPERATION, "init_instruments"): "op",
    (CATEGORY_OPERATION, "reset_instruments"): "op",
    (CATEGORY_OPERATION, "fixture_ready"): "op",
    (CATEGORY_OPERATION, "power_on"): "op",
    (CATEGORY_OPERATION, "power_off"): "op",
    (CATEGORY_OPERATION, "daq_ai_start"): "op",
    (CATEGORY_OPERATION, "daq_ai_end"): "op",
    (CATEGORY_OPERATION, "delay"): "op",

    (CATEGORY_CONSOLE, "serial"): "Console_serial",
    (CATEGORY_CONSOLE, "ssh"): "Console_ssh",
    (CATEGORY_CONSOLE, "cli"): "Console_cli",

    (CATEGORY_MESSAGE, "ok"): "MessageOK",
    (CATEGORY_MESSAGE, "yesno"): "MessageYesNo",
    (CATEGORY_MESSAGE, "gostop"): "MessageGoStop",
    (CATEGORY_MESSAGE, "ok_console"): "MessageOKtoConsole",
    (CATEGORY_MESSAGE, "yesno_console"): "MessageYesNotoConsole",
    (CATEGORY_MESSAGE, "gostop_console"): "MessageGoStoptoConsole",

    (CATEGORY_TRANSFER, "sftp_put"): "SSH SFTP: Push file to DUT",
    (CATEGORY_TRANSFER, "sftp_get"): "SSH SFTP: Pull file from DUT",
    (CATEGORY_TRANSFER, "serial_put"): "SerialPush",
    (CATEGORY_TRANSFER, "serial_pull"): "SerialPull",

    (CATEGORY_EXTERNAL_GUI, "flash"): "MessageGoStop",
    (CATEGORY_EXTERNAL_GUI, "test"): "MessageYesNo",

    (CATEGORY_WIFI, "scan"): "Wifi_Scan",
    (CATEGORY_WIFI, "ping"): "Wifi_Ping",
    (CATEGORY_WIFI, "iperf"): "Wifi_Iperf",

    (CATEGORY_BLUETOOTH, "rssi"): "BT_RSSI",
    (CATEGORY_BLUETOOTH, "pair"): "BT_Pair",
    (CATEGORY_BLUETOOTH, "tone"): "BT_Tone",
}

VERDICT_PASS = "pass"
VERDICT_FAIL = "fail"
VERDICT_ABORT = "abort"

#: ExternalGui verdict dialogs: flash -> Go / Stop, test -> Yes / No.
#: A negative answer is a FAIL and aborts the run immediately (no
#: on_fail fallback).
EXTERNAL_GUI_VERDICTS = {
    "flash": {"dialog": "MessageGoStop", "positive": VERDICT_PASS,
              "negative": VERDICT_FAIL, "abort_on_negative": True},
    "test": {"dialog": "MessageYesNo", "positive": VERDICT_PASS,
             "negative": VERDICT_FAIL, "abort_on_negative": True},
}

#: hard-coded window-close (X) answer of each Message sub-type.
#: gostop* answers Stop = FAIL + immediate abort.
MESSAGE_CLOSE_ACTION = {
    "ok": VERDICT_PASS,
    "ok_console": VERDICT_PASS,
    "yesno": VERDICT_FAIL,
    "yesno_console": VERDICT_FAIL,
    "gostop": VERDICT_ABORT,
    "gostop_console": VERDICT_ABORT,
}

#: the Message sub-types whose close answer also stops the run
MESSAGE_CLOSE_ABORTS = ("gostop", "gostop_console")
