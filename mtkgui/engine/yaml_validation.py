# -*- coding: utf-8 -*-
"""Project YAML validation on LOAD (M39, phase 1).

Owner direction 2026-10-30: validate when a project YAML is LOADED -
never silently keep runtime compatibility.  Every issue carries a fix
hint (which section to delete / change) so the operator can repair the
file, or create a new one.

Framework:
    validate_project_yaml(doc) -> list[YamlIssue]
    YamlIssue = (severity, message, location)

Rules are registered in ``_RULES`` and run in order; new rules are
added incrementally (phase 1 covers the retired flash operations).
severity="error" BLOCKS the load; severity="warning" is reported but
the load proceeds.
"""
from __future__ import annotations

from dataclasses import dataclass

SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"

#: step names retired in M33 (Flash_GUI replaces them)
RETIRED_FLASH_STEPS = ("Flash FAT Firmware", "Flash OOBE Firmware")

#: sequence sections scanned for retired steps: (label, yaml key)
_SEQUENCE_SECTIONS = (
    ("ict", "ict_test_cases"),
    ("fct", "fct_test_cases"),
)


@dataclass
class YamlIssue:
    """One load-time validation finding."""

    severity: str
    message: str
    location: str

    def as_line(self) -> str:
        """One readable line (severity + location + fix hint)."""
        return f"{self.severity.upper()} {self.location}: {self.message}"


#: registered rules: callable(doc) -> list[YamlIssue]
_RULES: list = []


def register_rule(fn):
    """Register a validation rule (decorator)."""
    _RULES.append(fn)
    return fn


def rule_retired_flash_steps(doc: dict) -> list[YamlIssue]:
    """Phase-1 rule: the M33-retired flash operations may not appear in
    an ICT / FCT sequence - the rows must be deleted or replaced."""
    issues: list[YamlIssue] = []
    workflow = (doc or {}).get("test_workflow") or {}
    for label, key in _SEQUENCE_SECTIONS:
        for index, row in enumerate(workflow.get(key) or []):
            if not isinstance(row, dict):
                continue
            name = str(row.get("name") or "").strip()
            if name not in RETIRED_FLASH_STEPS:
                continue
            issues.append(YamlIssue(
                SEVERITY_ERROR,
                f"step row {name!r} uses the retired flash operation - "
                f"delete the row {name!r} under {label}: {key} or replace "
                f"it with a Flash_GUI step",
                f"{key}[{index}].name"))
    return issues


_RULES.append(rule_retired_flash_steps)


def _carries_retired_console_login(row: dict) -> bool:
    """M83: True when a project row still expands the retired login step.

    The published marker carries ``params.fct_console_login`` (the
    built step) or ``params.kind == "login"``; both name the removed
    row type.  Read-only: nothing here rewrites the row."""
    marker = ((row.get("op_params") or {}).get("fct_step") or {})
    params = dict(marker.get("params") or {})
    return (bool(params.get("fct_console_login"))
            or str(params.get("kind") or "") == "login")


def rule_retired_console_login_rows(doc: dict) -> list[YamlIssue]:
    """M83: ``Console: Login to the DUT`` is retired - a project YAML
    still carrying the row is an ERROR that names the replacement."""
    from .fct_test_config import retired_console_login_message
    issues: list[YamlIssue] = []
    workflow = (doc or {}).get("test_workflow") or {}
    for label, key in _SEQUENCE_SECTIONS:
        for index, row in enumerate(workflow.get(key) or []):
            if not isinstance(row, dict) or not _carries_retired_console_login(
                    row):
                continue
            name = str(row.get("name") or "").strip()
            issues.append(YamlIssue(
                SEVERITY_ERROR,
                retired_console_login_message(name),
                f"{key}[{index}].name"))
    return issues


_RULES.append(rule_retired_console_login_rows)


def _retired_network_op_name(row: dict) -> str:
    """M83: the retired op name a legacy row still expands, else ``""``.

    Reads the existing op payload only (``op_params.op`` /
    ``op_params.type`` and the published ``fct_step.params``); a row
    named like an op but not carrying it (kind != "op") is left alone."""
    from .steps import RETIRED_NETWORK_OPS
    op = dict(row.get("op_params") or {})
    marker = dict(op.get("fct_step") or {})
    params = dict(marker.get("params") or {})
    for candidate in (op.get("op"), params.get("op")):
        text = str(candidate or "")
        if text in RETIRED_NETWORK_OPS:
            return text
    if str(row.get("kind") or "") == "op":
        name = str(row.get("name") or "")
        if name in RETIRED_NETWORK_OPS:
            return name
    op_type = str(op.get("type") or params.get("type") or "")
    if op_type == "wifi_connect":
        return RETIRED_NETWORK_OPS[0]
    if op_type == "lan_setup":
        return RETIRED_NETWORK_OPS[1]
    return ""


def rule_retired_network_ops(doc: dict) -> list[YamlIssue]:
    """M83: the two M41 network-setup operations are retired - a project
    YAML still carrying one is an ERROR that names the replacement."""
    from .steps import retired_network_op_message
    issues: list[YamlIssue] = []
    workflow = (doc or {}).get("test_workflow") or {}
    for label, key in _SEQUENCE_SECTIONS:
        for index, row in enumerate(workflow.get(key) or []):
            if not isinstance(row, dict):
                continue
            name = _retired_network_op_name(row)
            if not name:
                continue
            issues.append(YamlIssue(
                SEVERITY_ERROR,
                retired_network_op_message(name),
                f"{key}[{index}].name"))
    return issues


_RULES.append(rule_retired_network_ops)


#: M83/C7: the exact ERROR text naming the missing SSH channel.
SFTP_NEEDS_SSH_MESSAGE = ("SSH SFTP steps need at least one SSH channel — "
                          "add it in the Console panel (Test Work Flow page)")


def _row_is_sftp_transfer(row: dict) -> bool:
    """M83/C7: True when the row is an SSH SFTP push/pull.

    Reads existing row data only (the authored ``kind`` label or the
    published ``fct_step.params`` kind / action)."""
    if not isinstance(row, dict):
        return False
    kind = str(row.get("kind") or "")
    if "SFTP" in kind.upper():
        return True
    marker = dict((row.get("op_params") or {}).get("fct_step") or {})
    params = dict(marker.get("params") or {})
    return (str(params.get("kind") or "") in ("sftp_put", "sftp_get")
            or str(params.get("action") or "") in ("sftp_put", "sftp_get"))


def _ssh_channel_entries(doc: dict) -> list:
    """The project's configured SSH console channels (``console`` section)."""
    entries = (doc or {}).get("console") or []
    return [entry for entry in entries
            if isinstance(entry, dict)
            and str(entry.get("kind") or "") == "ssh"]


def rule_sftp_needs_ssh_channel(doc: dict,
                                connected_keys=None) -> list[YamlIssue]:
    """M83/C7: an SFTP row needs a configured SSH channel, and the run
    needs that channel connected.

    * SFTP row present, no SSH channel in the ``console`` section ->
      ERROR (the sequence cannot execute the transfer);
    * SFTP row present, SSH channel configured but none of the
      configured keys is connected -> warning (a load-time / save-time
      advisory; the runtime pre-run check refuses the run).

    ``connected_keys`` is the set of channel keys currently connected.
    ``None`` means "connection state unknown" -> the warning is not
    emitted (load time never guesses).
    """
    workflow = (doc or {}).get("test_workflow") or {}
    rows = [row for row in (workflow.get("fct_test_cases") or [])
            if isinstance(row, dict)]
    sftp_rows = [row for row in rows if _row_is_sftp_transfer(row)]
    if not sftp_rows:
        return []
    entries = _ssh_channel_entries(doc)
    if not entries:
        return [YamlIssue(SEVERITY_ERROR, SFTP_NEEDS_SSH_MESSAGE,
                          "console")]
    if connected_keys is None:
        return []
    # the console section is applied in row order: ssh entries become
    # ssh1, ssh2 ... (multi_console.apply_yaml_channels)
    ssh_keys = [f"ssh{i + 1}" for i in range(len(entries))]
    if any(key in connected_keys for key in ssh_keys):
        return []
    return [YamlIssue(
        SEVERITY_WARNING,
        "the SSH channel is configured but not connected — connect it in "
        "the Console panel (Test Work Flow page) before the run",
        "console")]


_RULES.append(rule_sftp_needs_ssh_channel)


#: M83/C8: the removed opt-in key.
LEGACY_SEND_CONSOLE_ANSWER_MSG = (
    "send_console_answer was removed — the answer is sent only by the "
    "*toConsole kinds")
#: M83/C8: answer payloads stored on a plain Message kind are ignored.
LEGACY_PLAIN_PAYLOAD_MSG = (
    "send_yes / send_no are ignored — a plain Message kind never writes "
    "to the console")


def _is_plain_message_row(row: dict) -> bool:
    """True when the row is one of the three plain Message kinds."""
    from .fct_test_config import PLAIN_MESSAGE_KINDS
    label = str(row.get("type") or row.get("kind") or "")
    if label in PLAIN_MESSAGE_KINDS:
        return True
    if label.lower() == "message":
        # a ConsoleCommand-shaped row: the kind is carried by the wait
        # flag (a *toConsole row always waits)
        return not bool(row.get("wait_enabled", False))
    return False


def _legacy_message_rows(doc: dict):
    """Every stored Message-row mapping the document carries (yielded as
    ``(location, name, mapping)``).  Reads existing keys only."""
    import yaml as _yaml
    workflow = (doc or {}).get("test_workflow") or {}
    for index, row in enumerate(workflow.get("fct_test_cases") or []):
        if not isinstance(row, dict):
            continue
        marker = dict((row.get("op_params") or {}).get("fct_step") or {})
        params = dict(marker.get("params") or {})
        # the published case carries the six-kind label - expose it to
        # the plain-row check without adding a new YAML field
        params.setdefault("kind", str(row.get("kind") or marker.get("type")
                                      or ""))
        if str(marker.get("step_type") or "") == "GUI_CONFIRM" \
                or str(row.get("kind") or "") in (
                    "MessageOK", "MessageYesNo", "MessageGoStop",
                    "MessageOKtoConsole", "MessageYesNotoConsole",
                    "MessageGoStoptoConsole"):
            yield (f"fct_test_cases[{index}]",
                   str(row.get("name") or marker.get("name") or ""), params)
    state = (doc or {}).get("yaml_build_state") or {}
    params = (((state.get("modules") or {}).get("fct_build") or {})
              .get("params")) or {}
    text = str(params.get("fct_steps_yaml") or "")
    if text.strip():
        try:
            node = _yaml.safe_load(text) or {}
        except _yaml.YAMLError:
            node = {}
        fct = (node.get("fct") if isinstance(node, dict) else None) or {}
        for index, step in enumerate(fct.get("steps") or []):
            if not isinstance(step, dict):
                continue
            if str(step.get("type") or "") in (
                    "MessageOK", "MessageYesNo", "MessageGoStop",
                    "MessageOKtoConsole", "MessageYesNotoConsole",
                    "MessageGoStoptoConsole"):
                yield (f"fct_steps_yaml.steps[{index}]",
                       str(step.get("name") or ""), step)
    text = str(params.get("fct_test_config_yaml") or "")
    if text.strip():
        try:
            node = _yaml.safe_load(text) or {}
        except _yaml.YAMLError:
            node = {}
        cfg = (node.get("fct_test_config")
               if isinstance(node, dict) else None) or {}
        for index, cmd in enumerate(
                (cfg.get("console") or {}).get("test_commands") or []):
            if isinstance(cmd, dict) and str(cmd.get("kind") or "") == "message":
                yield (f"test_commands[{index}]",
                       str(cmd.get("name") or ""), cmd)


def rule_legacy_message_console_keys(doc: dict) -> list[YamlIssue]:
    """M83/C8: report the removed console-answer keys.

    * ``send_console_answer`` present -> warning; the value is ignored.
    * a PLAIN Message row still carrying ``send_yes`` / ``send_no`` ->
      one warning per row; the values are ignored, never stripped.
    """
    issues: list[YamlIssue] = []
    seen: set = set()
    for location, name, row in _legacy_message_rows(doc):
        if "send_console_answer" in row:
            key = ("removed", name)
            if key not in seen:
                seen.add(key)
                issues.append(YamlIssue(SEVERITY_WARNING,
                                        LEGACY_SEND_CONSOLE_ANSWER_MSG,
                                        location))
        if (_is_plain_message_row(row)
                and ("send_yes" in row or "send_no" in row)):
            key = ("payload", name)
            if key not in seen:
                seen.add(key)
                issues.append(YamlIssue(
                    SEVERITY_WARNING,
                    f"row {name!r}: {LEGACY_PLAIN_PAYLOAD_MSG}", location))
    return issues


_RULES.append(rule_legacy_message_console_keys)


#: M79: row kinds that only report that the step ran / were skipped.
#: They can never judge the DUT itself, so they do not make a sequence
#: a "real test" sequence.  Everything else (console capture / wait,
#: WIFI, Bluetooth, SFTP, SendtoCLI with expectations, human-confirm
#: gates, external-tool message checks, ICT measurements) counts.
_NON_TEST_KINDS = frozenset({
    "op", "delay", "messageok", "messageoktoconsole",
})

#: stage name fragment -> (canonical label, sequence key)
_STAGE_SECTIONS = (
    ("ict", "ICT", "ict_test_cases"),
    ("fct", "FCT", "fct_test_cases"),
)


def _row_is_real_test(row: dict) -> bool:
    """True when the row can produce a PASS/FAIL about the DUT.

    Not a real test: a skipped / disabled row (runs as Ignore), an
    ``op`` row (reports Done), a Delay, and a notice-only MessageOK
    row.  The check reads EXISTING row data only - no new YAML field."""
    if not isinstance(row, dict):
        return False
    if row.get("skip") is True or row.get("enable") is False:
        return False
    marker = ((row.get("op_params") or {}).get("fct_step") or {})
    params = dict(marker.get("params") or {})
    if params.get("skip") is True or params.get("op"):
        return False
    if params.get("fct_delay_ms") is not None:
        return False
    kind = str(row.get("kind") or marker.get("step_type")
               or marker.get("type") or "").strip().lower()
    return kind not in _NON_TEST_KINDS


def rule_sequence_has_real_test(doc: dict) -> list[YamlIssue]:
    """M79: every ENABLED, explicitly configured stage must contain at
    least one real test (a row that can judge the DUT, not only report
    Done / Ignore).  A disabled stage (and a stage with no sequence
    section at all) is exempt."""
    from .sequence import _stage_flow
    issues: list[YamlIssue] = []
    workflow = (doc or {}).get("test_workflow") or {}
    checked: set = set()
    for entry in _stage_flow(doc or {}):
        if not entry.get("enable", True):
            continue
        low = str(entry.get("stage") or "").lower()
        label, key = "", ""
        for fragment, canonical, section in _STAGE_SECTIONS:
            if fragment in low:
                label, key = canonical, section
                break
        if not key or key in checked:
            continue
        if key not in workflow:
            # no sequence configured for this stage -> nothing to judge
            continue
        checked.add(key)
        rows = [row for row in (workflow.get(key) or [])
                if isinstance(row, dict)]
        if not rows:
            issues.append(YamlIssue(
                SEVERITY_ERROR,
                f"{label} sequence is empty - no test is defined",
                key))
            continue
        if not any(_row_is_real_test(row) for row in rows):
            issues.append(YamlIssue(
                SEVERITY_ERROR,
                f"{label} sequence contains no valid test (every row is "
                f"Done / Ignore / Delay / notice) - add at least one real "
                f"test",
                key))
    return issues


_RULES.append(rule_sequence_has_real_test)


def validate_project_yaml(doc: dict, connected_keys=None) -> list[YamlIssue]:
    """Run every registered rule on a parsed project YAML document.

    ``connected_keys`` (M83/C7): the console channel keys that are
    currently connected, passed to the rules that can use it. ``None``
    means the caller has no runtime state - the rules then report only
    what the document itself proves."""
    issues: list[YamlIssue] = []
    for rule in _RULES:
        if "connected_keys" in rule.__code__.co_varnames[
                :rule.__code__.co_argcount]:
            issues.extend(rule(doc, connected_keys=connected_keys) or [])
        else:
            issues.extend(rule(doc) or [])
    return issues


def blocking_issues(issues: list[YamlIssue]) -> list[YamlIssue]:
    """Only the issues that must stop the load (severity == error)."""
    return [issue for issue in issues
            if issue.severity == SEVERITY_ERROR]


def format_issues(issues: list[YamlIssue]) -> str:
    """Dialog text: one line per issue + the repair suggestion."""
    lines = [issue.as_line() for issue in issues]
    lines.append("")
    lines.append("Edit the YAML file to delete / change the listed rows, "
                 "or create a new YAML project.")
    return "\n".join(lines)
