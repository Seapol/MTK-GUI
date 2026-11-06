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


def validate_project_yaml(doc: dict) -> list[YamlIssue]:
    """Run every registered rule on a parsed project YAML document."""
    issues: list[YamlIssue] = []
    for rule in _RULES:
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
