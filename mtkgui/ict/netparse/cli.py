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

from .export import result_to_csv, result_to_json
from .parser import parse_nets_file


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m mtkgui.ict.netparse",
        description="Parse a netlist (SPF / Allegro NET / PSTXNET / "
                    "Allegro Report) and export the ICT testable nets.")
    parser.add_argument("input", help="netlist file to parse")
    parser.add_argument("--rules", default=None,
                        help="JSON file with classification rules "
                             "(power / se_clock / diff_pair / exclude)")
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


def main(argv: list[str] | None = None) -> int:
    """Run the CLI; returns the process exit code."""
    args = _build_parser().parse_args(argv)
    try:
        rules = _read_rules(args.rules)
        result = parse_nets_file(args.input, rules)
        if args.format == "csv":
            text = result_to_csv(result)
        else:
            text = result_to_json(result, indent=max(0, args.indent))
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
