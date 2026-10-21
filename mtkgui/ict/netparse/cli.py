# -*- coding: utf-8 -*-
"""Command-line entry: ``python -m mtkgui.ict.netparse``.

Contract::

    python -m mtkgui.ict.netparse <input-file> [--rules RULES.json]
                                  [--format json|csv] [--output FILE]
                                  [--indent N]

Failures print ``error: <reason>`` to stderr and exit 2 (no partial
output on stdout).
"""
from __future__ import annotations

import argparse
import json
import sys

from .capacity import parse_limits
from .export import result_to_csv, result_to_json
from .parser import apply_user_overrides, parse_nets_file


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m mtkgui.ict.netparse",
        description="Parse a netlist (SPF / Allegro NET / PSTXNET / "
                    "Allegro Report) and export the ICT testable nets.")
    parser.add_argument("input", help="netlist file to parse")
    parser.add_argument("--rules", default=None,
                        help="JSON file with classification rules "
                             "(power / se_clock / diff_pair / exclude)")
    parser.add_argument("--library", default=None,
                        help="JSON/YAML file mapping refdes -> "
                             "{'part_number': str} (M2 device-role "
                             "knowledge base, built from the BOM)")
    parser.add_argument("--limits", default=None,
                        help="instrument capacity overrides, "
                             "\"power=80,rails=12,clock_lf=1,"
                             "clock_hf=2,ctrl=24\" (defaults)")
    parser.add_argument("--apply-overrides", default=None,
                        help="JSON file with a {net: class} user-"
                             "override map (B5 round-trip; the user "
                             "choice beats the algorithmic class)")
    parser.add_argument("--format", choices=("json", "csv"),
                        default="json", help="output format (default json)")
    parser.add_argument("--output", default=None,
                        help="write the result to FILE (default stdout)")
    parser.add_argument("--indent", type=int, default=2,
                        help="JSON indent (0 = compact; default 2)")
    return parser


def _read_rules(path: str | None) -> dict | None:
    if not path:
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except OSError as exc:
        raise ValueError(f"cannot read rules file: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid rules JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("rules JSON must be an object")
    return data


def _read_library(path: str | None) -> dict[str, str] | None:
    """Read the optional refdes -> part_number library map."""
    if not path:
        return None
    try:
        if path.lower().endswith((".yaml", ".yml")):
            import yaml
            with open(path, "r", encoding="utf-8") as handle:
                data = yaml.safe_load(handle)
        else:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
    except OSError as exc:
        raise ValueError(f"cannot read library file: {exc}") from exc
    except Exception as exc:
        raise ValueError(f"invalid library file: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("library file must map refdes -> part info")
    library: dict = {}
    for refdes, info in data.items():
        if isinstance(info, dict):
            entry = {"part_number": str(info.get("part_number") or ""),
                     "description": str(info.get("description") or ""),
                     "value": str(info.get("value") or "")}
            if any(entry.values()):
                library[str(refdes)] = entry
        else:
            part = str(info)
            if part:
                library[str(refdes)] = part
    return library


def _read_overrides(path: str | None) -> dict[str, str]:
    """Read the B5 ``{net: class}`` user-override map."""
    if not path:
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except OSError as exc:
        raise ValueError(f"cannot read overrides file: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid overrides JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("overrides file must map net -> class")
    return {str(k): str(v) for k, v in data.items()}


def main(argv: list[str] | None = None) -> int:
    """Run the CLI; returns the process exit code."""
    args = _build_parser().parse_args(argv)
    try:
        rules = _read_rules(args.rules)
        library = _read_library(args.library)
        limits = parse_limits(args.limits)
        overrides = _read_overrides(args.apply_overrides)
        result = parse_nets_file(args.input, rules, library)
        if overrides:
            apply_user_overrides(result, overrides)
        if args.format == "csv":
            text = result_to_csv(result, limits, library)
        else:
            text = result_to_json(result, limits, library,
                                  indent=max(0, args.indent))
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.output:
        try:
            with open(args.output, "w", encoding="utf-8", newline="") \
                    as handle:
                handle.write(text)
        except OSError as exc:
            print(f"error: cannot write output: {exc}", file=sys.stderr)
            return 2
    else:
        sys.stdout.write(text)
        if not text.endswith("\n"):
            sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
