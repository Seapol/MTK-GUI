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
