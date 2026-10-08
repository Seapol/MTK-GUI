# -*- coding: utf-8 -*-
"""Credential layer (D4-A signed off, spec §7.1): OS keyring with an
EXPLICIT environment-variable fallback — never a silent downgrade to
plaintext.

Lookup order for `get_credential(ref)`:

1. OS keyring  (service "mtk-gui", account = ref);
2. environment variable  MTK_CRED_<REF uppercased>  — with a LOUD
   warning returned alongside the value (the caller MUST surface it:
   Event Log + UI banner on the affected channel dialog);
3. neither -> :class:`CredentialUnavailable` (the channel open fails
   with a clear reason; nothing is guessed).

Windows packaging (real-machine batch acceptance): `keyring` needs
hidden imports (keyring.backends.Windows) in the PyInstaller specs —
see docs/fct/B4-FCT-Execution-Design.md §6.
"""
from __future__ import annotations

import os

SERVICE = "mtk-gui"
ENV_PREFIX = "MTK_CRED_"


class CredentialUnavailable(RuntimeError):
    """No keyring entry AND no environment fallback for a ref."""


class CredentialWarning(RuntimeWarning):
    """The env fallback served the value — the caller MUST show this."""


def _keyring_module():
    """Import keyring lazily (optional baseline dependency)."""
    try:
        import keyring  # noqa: PLC0415 - optional at runtime
        import keyring.errors  # noqa: PLC0415
        return keyring
    except Exception:  # noqa: BLE001 - backend absence is expected
        return None


def get_credential(ref: str) -> tuple:
    """Resolve one credential.

    Returns:
        (value, warning) — `warning` is a str (possibly empty) that the
        caller MUST surface when non-empty (env fallback used).

    Raises:
        CredentialUnavailable: neither source has the ref.
    """
    ref = str(ref or "").strip()
    if not ref:
        raise CredentialUnavailable("empty credential ref")
    kr = _keyring_module()
    if kr is not None:
        try:
            value = kr.get_password(SERVICE, ref)
            if value:
                return value, ""
        except Exception:  # noqa: BLE001 - backend failure = fallback
            pass
    env_key = ENV_PREFIX + ref.upper().replace("-", "_")
    value = os.environ.get(env_key)
    if value:
        return value, (f"keyring unavailable - using environment "
                       f"fallback for {ref}")
    raise CredentialUnavailable(
        f"no credential for {ref!r} (keyring"
        f"{' unavailable' if kr is None else ' empty'} and {env_key} "
        "not set)")


def set_credential(ref: str, value: str) -> tuple:
    """Store one credential in the OS keyring.

    Returns:
        (ok, warning) - ok False means the keyring refused the write;
        the caller must then tell the operator to use the env fallback
        (this module never writes plaintext files).
    """
    kr = _keyring_module()
    if kr is None:
        return False, ("keyring unavailable - set the environment "
                       f"variable {ENV_PREFIX}{ref.upper()} instead")
    try:
        kr.set_password(SERVICE, str(ref), str(value))
        return True, ""
    except Exception as exc:  # noqa: BLE001 - backend refusal
        return False, f"keyring write failed: {exc}"


def delete_credential(ref: str) -> bool:
    """Best-effort removal (password reset / ops scenario 7.2)."""
    kr = _keyring_module()
    if kr is None:
        return False
    try:
        kr.delete_password(SERVICE, str(ref))
        return True
    except Exception:  # noqa: BLE001 - absence is fine
        return False
