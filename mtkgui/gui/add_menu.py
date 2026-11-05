# -*- coding: utf-8 -*-
"""M48: the ONE shared ICT / FCT Add menu.

Both the ICT step editor (``StepsEditorDialog._make_add_menu``) and the
FCT sequence table (``FCTTestConfigWidget._cmd_row_buttons``) render
this structure - no caller builds a flat menu any more.

Every entry belongs to exactly one DOMAIN:

* ``standard`` - usable in both sequences (the Operation group);
* ``ict``      - ICT only (the ICT Measurements group);
* ``fct``      - FCT only (File Transfer / Network / Console / Message
  (Console) / Wi-Fi Tests / Bluetooth Tests / Flash).

A non-applicable domain is GRAYED OUT (disabled, never removed) with a
tooltip naming the domain, so the operator can see what exists.

Engine catalogs (``OP_STEPS`` / ``NETWORK_OPS`` / ``DIO_OPS`` /
``STEP_TYPE_*`` / ``KIND_*``) are untouched: only the menu grouping and
ownership live here.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu

from mtkgui.engine.fct_test_config import (
    STEP_TYPE_BT_PAIR,
    STEP_TYPE_BT_RSSI,
    STEP_TYPE_BT_TONE,
    STEP_TYPE_CONSOLE_CLI,
    STEP_TYPE_CONSOLE_LOGIN,
    STEP_TYPE_CONSOLE_SERIAL,
    STEP_TYPE_CONSOLE_SSH,
    STEP_TYPE_FLASH_GUI,
    STEP_TYPE_MESSAGE_GOSTOP,
    STEP_TYPE_MESSAGE_GOSTOP_WAIT,
    STEP_TYPE_MESSAGE_OK,
    STEP_TYPE_MESSAGE_OK_WAIT,
    STEP_TYPE_MESSAGE_YESNO,
    STEP_TYPE_MESSAGE_YESNO_WAIT,
    STEP_TYPE_SERIAL_PULL,
    STEP_TYPE_SERIAL_PUT,
    STEP_TYPE_SFTP_GET,
    STEP_TYPE_SFTP_PUT,
    STEP_TYPE_WIFI_IPERF,
    STEP_TYPE_WIFI_PING,
    STEP_TYPE_WIFI_SCAN,
)
from mtkgui.engine.steps import (
    DIO_OPS,
    LAN_SETUP_OP,
    METHOD_R_GND,
    OP_STEPS,
    WIFI_CONNECT_OP,
)

DOMAIN_STANDARD = "standard"
DOMAIN_ICT = "ict"
DOMAIN_FCT = "fct"

ICT_ONLY_TOOLTIP = "ICT-only step — not available in an FCT sequence"
FCT_ONLY_TOOLTIP = "FCT-only step — not available in an ICT sequence"

#: the domain a given sequence cannot use
TARGET_ONLY = {"ict": DOMAIN_FCT, "fct": DOMAIN_ICT}

#: submenu titles, in menu order ("Operation" stays FIRST - M43)
OPERATION = "Operation"
ICT_MEASUREMENTS = "ICT Measurements"
FILE_TRANSFER = "File Transfer"
NETWORK = "Network"
CONSOLE = "Console"
MESSAGE_CONSOLE = "Message (Console)"
WIFI_TESTS = "Wi-Fi Tests"
BLUETOOTH_TESTS = "Bluetooth Tests"
FLASH = "Flash"

MENU_TITLES = (OPERATION, ICT_MEASUREMENTS, FILE_TRANSFER, NETWORK, CONSOLE,
               MESSAGE_CONSOLE, WIFI_TESTS, BLUETOOTH_TESTS, FLASH)

DELAY_LABEL = "Delay — plain wait (ms)"


@dataclass(frozen=True)
class AddEntry:
    """One Add-menu entry: which group owns it, who may use it, and the
    canonical payload key the callers translate into their step model."""

    group: str
    domain: str
    label: str
    key: str
    op_name: str = ""


def _op_entries(names, group=OPERATION, domain=DOMAIN_STANDARD):
    return [AddEntry(group, domain, f"Operation: {name}", f"op:{name}", name)
            for name in names]


#: the standard Operation group: 9 catalog operations + Delay + the three
#: plain operator dialogs (M48 moved them out of the Message group)
STANDARD_OPS = tuple(name for name in OP_STEPS
                     if name not in DIO_OPS
                     and name not in (WIFI_CONNECT_OP, LAN_SETUP_OP))

ADD_ENTRIES = tuple(
    _op_entries(STANDARD_OPS) + [
        AddEntry(OPERATION, DOMAIN_STANDARD, DELAY_LABEL, "delay"),
        AddEntry(OPERATION, DOMAIN_STANDARD, STEP_TYPE_MESSAGE_OK,
                 f"step:{STEP_TYPE_MESSAGE_OK}"),
        AddEntry(OPERATION, DOMAIN_STANDARD, STEP_TYPE_MESSAGE_YESNO,
                 f"step:{STEP_TYPE_MESSAGE_YESNO}"),
        AddEntry(OPERATION, DOMAIN_STANDARD, STEP_TYPE_MESSAGE_GOSTOP,
                 f"step:{STEP_TYPE_MESSAGE_GOSTOP}"),
    ] + [
        # M48: ICT-only measurements (the two DIO operations moved here
        # from Operation - they need the ICT Control IO Nets)
        AddEntry(ICT_MEASUREMENTS, DOMAIN_ICT,
                 "R-GND — rail-to-ground impedance",
                 f"measure:{METHOD_R_GND}"),
        AddEntry(ICT_MEASUREMENTS, DOMAIN_ICT,
                 "DAQ AI Sequences — power-rails up sequence",
                 "measure:DAQ AI"),
        AddEntry(ICT_MEASUREMENTS, DOMAIN_ICT, "Voltage — power rail level",
                 "measure:Power Voltage"),
        AddEntry(ICT_MEASUREMENTS, DOMAIN_ICT,
                 "Clock Hz — clock frequency", "measure:Clock Hz"),
        AddEntry(ICT_MEASUREMENTS, DOMAIN_ICT, DIO_OPS[0],
                 f"op:{DIO_OPS[0]}", DIO_OPS[0]),
        AddEntry(ICT_MEASUREMENTS, DOMAIN_ICT, DIO_OPS[1],
                 f"op:{DIO_OPS[1]}", DIO_OPS[1]),
    ] + [
        # FCT-only groups
        AddEntry(FILE_TRANSFER, DOMAIN_FCT, STEP_TYPE_SFTP_PUT,
                 f"step:{STEP_TYPE_SFTP_PUT}"),
        AddEntry(FILE_TRANSFER, DOMAIN_FCT, STEP_TYPE_SFTP_GET,
                 f"step:{STEP_TYPE_SFTP_GET}"),
        AddEntry(FILE_TRANSFER, DOMAIN_FCT, STEP_TYPE_SERIAL_PUT,
                 f"step:{STEP_TYPE_SERIAL_PUT}"),
        AddEntry(FILE_TRANSFER, DOMAIN_FCT, STEP_TYPE_SERIAL_PULL,
                 f"step:{STEP_TYPE_SERIAL_PULL}"),
        AddEntry(NETWORK, DOMAIN_FCT, WIFI_CONNECT_OP,
                 f"op:{WIFI_CONNECT_OP}", WIFI_CONNECT_OP),
        AddEntry(NETWORK, DOMAIN_FCT, LAN_SETUP_OP,
                 f"op:{LAN_SETUP_OP}", LAN_SETUP_OP),
        AddEntry(CONSOLE, DOMAIN_FCT, STEP_TYPE_CONSOLE_SERIAL,
                 f"step:{STEP_TYPE_CONSOLE_SERIAL}"),
        AddEntry(CONSOLE, DOMAIN_FCT, STEP_TYPE_CONSOLE_SSH,
                 f"step:{STEP_TYPE_CONSOLE_SSH}"),
        AddEntry(CONSOLE, DOMAIN_FCT, STEP_TYPE_CONSOLE_CLI,
                 f"step:{STEP_TYPE_CONSOLE_CLI}"),
        # M76/D3: operator-authored DUT login row (never auto-inserted)
        AddEntry(CONSOLE, DOMAIN_FCT, STEP_TYPE_CONSOLE_LOGIN,
                 f"step:{STEP_TYPE_CONSOLE_LOGIN}"),
        AddEntry(MESSAGE_CONSOLE, DOMAIN_FCT, STEP_TYPE_MESSAGE_OK_WAIT,
                 f"step:{STEP_TYPE_MESSAGE_OK_WAIT}"),
        AddEntry(MESSAGE_CONSOLE, DOMAIN_FCT, STEP_TYPE_MESSAGE_YESNO_WAIT,
                 f"step:{STEP_TYPE_MESSAGE_YESNO_WAIT}"),
        AddEntry(MESSAGE_CONSOLE, DOMAIN_FCT, STEP_TYPE_MESSAGE_GOSTOP_WAIT,
                 f"step:{STEP_TYPE_MESSAGE_GOSTOP_WAIT}"),
        AddEntry(WIFI_TESTS, DOMAIN_FCT, STEP_TYPE_WIFI_SCAN,
                 f"step:{STEP_TYPE_WIFI_SCAN}"),
        AddEntry(WIFI_TESTS, DOMAIN_FCT, STEP_TYPE_WIFI_PING,
                 f"step:{STEP_TYPE_WIFI_PING}"),
        AddEntry(WIFI_TESTS, DOMAIN_FCT, STEP_TYPE_WIFI_IPERF,
                 f"step:{STEP_TYPE_WIFI_IPERF}"),
        AddEntry(BLUETOOTH_TESTS, DOMAIN_FCT, STEP_TYPE_BT_RSSI,
                 f"step:{STEP_TYPE_BT_RSSI}"),
        AddEntry(BLUETOOTH_TESTS, DOMAIN_FCT, STEP_TYPE_BT_PAIR,
                 f"step:{STEP_TYPE_BT_PAIR}"),
        AddEntry(BLUETOOTH_TESTS, DOMAIN_FCT, STEP_TYPE_BT_TONE,
                 f"step:{STEP_TYPE_BT_TONE}"),
        AddEntry(FLASH, DOMAIN_FCT, STEP_TYPE_FLASH_GUI,
                 f"step:{STEP_TYPE_FLASH_GUI}"),
    ])


def entries_of(group: str, domain: str = "") -> list:
    """Entries of one group (optionally filtered by domain)."""
    return [e for e in ADD_ENTRIES
            if e.group == group and (not domain or e.domain == domain)]


@dataclass
class BuiltMenu:
    """The rendered menu plus the pieces callers keep for M37 gating."""

    menu: QMenu
    submenus: dict = field(default_factory=dict)
    by_label: dict = field(default_factory=dict)
    by_key: dict = field(default_factory=dict)
    entries: list = field(default_factory=list)


def build_add_menu(parent, target: str, on_entry,
                   gate=None, disable_groups=None) -> BuiltMenu:
    """Render the unified Add menu for one sequence domain.

    Args:
        parent: Qt parent for the QMenu (a button / dialog).
        target: "ict" or "fct" - the sequence being edited.
        on_entry: ``callable(AddEntry)`` - add the row / step directly.
        gate: optional ``callable(AddEntry) -> (enabled, tooltip)`` for
            the fine-grained M37 resource gating (returning None keeps
            the domain verdict).
        disable_groups: optional ``{submenu title: tooltip}`` for a
            caller that cannot express some groups (kept visible and
            grayed, M48 §2 rule).

    A group whose domain does not match ``target`` stays visible but is
    disabled with the domain tooltip (M48 §2).
    """
    built = BuiltMenu(menu=QMenu(parent))
    menu = built.menu
    extra_disabled = dict(disable_groups or {})
    for title in MENU_TITLES:
        group_entries = entries_of(title)
        # explicit parent: keeps the C++ submenu alive regardless of the
        # transient QAction wrappers the callers iterate (M48)
        sub = QMenu(title, menu)
        menu.addMenu(sub)
        sub.setToolTipsVisible(True)
        built.submenus[title] = sub
        blocked_domain = TARGET_ONLY[target]
        tip = ""
        if group_entries[0].domain == blocked_domain:
            tip = (ICT_ONLY_TOOLTIP if blocked_domain == DOMAIN_ICT
                   else FCT_ONLY_TOOLTIP)
        elif title in extra_disabled:
            tip = extra_disabled[title]
        if tip:
            sub.setEnabled(False)
            sub.menuAction().setEnabled(False)
            sub.menuAction().setToolTip(tip)
        for entry in group_entries:
            act = sub.addAction(entry.label,
                                lambda _checked=False, e=entry: on_entry(e))
            built.by_label[entry.label] = act
            built.by_key[entry.key] = act
            built.entries.append((entry, act))
            if tip:
                act.setToolTip(tip)
            elif gate is not None:
                verdict = gate(entry)
                if verdict is not None:
                    enabled, entry_tip = verdict
                    act.setEnabled(bool(enabled))
                    act.setToolTip(entry_tip or "")
    return built
