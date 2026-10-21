# -*- coding: utf-8 -*-
"""Headless ICT net parsing (no Qt, no ``mtkgui.gui`` imports).

Public API::

    from mtkgui.ict.netparse import parse_nets_file, parse_testable_nets

    result = parse_nets_file("board.net")
    print(result.summary())
"""
from .model import (CATEGORIES, CATEGORY_CLOCK,
                    CATEGORY_CONTROL_IO_LABEL, CATEGORY_GND,
                    CATEGORY_GPIO, CATEGORY_POWER,
                    NET_TYPE_CLOCK_SINGLE, NET_TYPE_DIFF_PAIR,
                    NET_TYPE_GND_REF, NET_TYPE_POWER, NET_TYPE_SIGNAL,
                    NET_TYPES, NetCollection, NetlistData, NetRecord,
                    ParseNetsResult)
from .netlist import (parse_netlist, parse_netlist_file,
                      read_text_any_encoding)
from .spf import SpfData, SpfParseError, cross_check_nets, parse_spf
from .formats import (clean_net_text, detect_netlist_format,
                      parse_allegro_report, parse_netlist_auto,
                      parse_pstxnet)
from .classify import classify_nets
from .rules import (DEFAULT_RULES, EXCLUDED_REASON as RULE_EXCLUDED_REASON,
                    RULE_SLOTS, apply_user_rules, classify_net,
                    exclude_pattern, validate_rules)
from .testpoints import select_test_points
from .parser import (EXCLUDED_REASON, parse_nets_file,
                     parse_testable_nets)
from .export import (RESULT_SCHEMA, result_to_csv, result_to_dict,
                     result_to_json)

__all__ = [
    "CATEGORIES", "CATEGORY_CLOCK", "CATEGORY_CONTROL_IO_LABEL",
    "CATEGORY_GND", "CATEGORY_GPIO", "CATEGORY_POWER",
    "NET_TYPE_CLOCK_SINGLE", "NET_TYPE_DIFF_PAIR", "NET_TYPE_GND_REF",
    "NET_TYPE_POWER", "NET_TYPE_SIGNAL", "NET_TYPES",
    "NetCollection", "NetlistData", "NetRecord", "ParseNetsResult",
    "parse_netlist", "parse_netlist_file", "read_text_any_encoding",
    "SpfData", "SpfParseError", "cross_check_nets", "parse_spf",
    "clean_net_text", "detect_netlist_format", "parse_allegro_report",
    "parse_netlist_auto", "parse_pstxnet", "classify_nets",
    "DEFAULT_RULES", "RULE_EXCLUDED_REASON", "RULE_SLOTS",
    "apply_user_rules", "classify_net", "exclude_pattern",
    "validate_rules", "select_test_points",
    "EXCLUDED_REASON", "parse_nets_file", "parse_testable_nets",
    "RESULT_SCHEMA", "result_to_csv", "result_to_dict",
    "result_to_json",
]
