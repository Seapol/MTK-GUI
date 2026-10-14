"""MTK GUI - Manufacturing Test Kit.

A dual-UART serial console for embedded board bring-up and
manufacturing-floor testing: one port connects to the DUT UART1, the
second port connects to either the DUT UART2 or a companion / test board.
"""

__version__ = "v1.0.0.0"
# THE single GUI version (user directive 2026-10-14): starts at
# v1.0.0.0 and is bumped ONLY on a Release commit - develop commits
# never change it.  Every release must record its changes in
# docs/help/version_history.md (Help > Version History) and the
# release entry is reviewed by the owner before publishing.
__app_name__ = "MTK"
