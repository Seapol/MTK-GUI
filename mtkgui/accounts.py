"""Station accounts - the supervisor credential lives here, never in the source.

The supervisor password is set once by the NXP owner at station setup
(``MTK_GUI.exe --set-supervisor-password``) and stored as a PBKDF2 hash with a
random salt in ``work/accounts/supervisor.json``.  Nothing in this repository
or in the shipped package carries a plaintext password: with no hash file the
supervisor login refuses and asks for the NXP owner.
"""

import base64
import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path

from .report_paths import work_dir

ACCOUNTS_DIR_NAME = "accounts"
SUPERVISOR_FILE = "supervisor.json"
KDF = "pbkdf2_sha256"
ITERATIONS = 600_000
SALT_BYTES = 16
MIN_LENGTH = 8
# The historical in-source value.  It is refused at setup because every build
# handed out so far shipped it, so people who should not hold it already know
# it.  Split literal so this file never contains the value itself.
RETIRED_DEFAULTS = ("n" "xp",)

_RECORD_KEYS = ("kdf", "iterations", "salt", "hash")


def accounts_dir() -> Path:
    """Station account folder inside the surviving ``work`` directory."""
    return work_dir() / ACCOUNTS_DIR_NAME


def supervisor_path() -> Path:
    """The supervisor hash file (created at setup, never shipped)."""
    return accounts_dir() / SUPERVISOR_FILE


def load_supervisor():
    """The stored supervisor record, or ``None`` when unusable.

    Missing, unreadable, malformed JSON, non-object or wrongly typed fields all
    mean "not configured" - this never raises.
    """
    try:
        data = json.loads(supervisor_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not all(k in data for k in _RECORD_KEYS):
        return None
    if not isinstance(data["kdf"], str):
        return None
    if not isinstance(data["salt"], str) or not isinstance(data["hash"], str):
        return None
    iterations = data["iterations"]
    if isinstance(iterations, bool) or not isinstance(iterations, int):
        return None
    return data


def is_configured() -> bool:
    """True when a usable supervisor hash file exists on this station."""
    return load_supervisor() is not None


def verify(password: str) -> bool:
    """True when ``password`` matches the stored hash.  Never raises."""
    record = load_supervisor()
    if not password or record is None:
        return False
    try:
        salt = base64.b64decode(record["salt"])
        expected = base64.b64decode(record["hash"])
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                                     salt, record["iterations"])
    except (TypeError, ValueError):
        return False
    return hmac.compare_digest(digest, expected)


def hash_password(password: str, iterations: int = ITERATIONS) -> dict:
    """Build the on-disk record for ``password`` (salt is random per call)."""
    salt = secrets.token_bytes(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt,
                                 iterations)
    return {
        "version": 1,
        "kdf": KDF,
        "iterations": iterations,
        "salt": base64.b64encode(salt).decode("ascii"),
        "hash": base64.b64encode(digest).decode("ascii"),
        "created": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _validate(password: str) -> None:
    """Refuse values that would make the station credential worthless."""
    if not password.strip():
        raise ValueError("the supervisor password must not be blank")
    if password.lower() in RETIRED_DEFAULTS:
        raise ValueError(
            "that value was the old built-in default - choose a new password")
    if len(password) < MIN_LENGTH:
        raise ValueError(
            f"the supervisor password must be at least {MIN_LENGTH} characters")


def set_password(password: str) -> Path:
    """Validate, write the hash record and return its path."""
    _validate(password)
    path = supervisor_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(hash_password(password), indent=2) + "\n",
                    encoding="utf-8")
    try:
        # POSIX: owner-only.  Windows has no equivalent, and ACLs are out of
        # scope - the station folder is the protection boundary.
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def clear_password() -> None:
    """Remove the hash file (rotation / tests).  Missing file is fine."""
    try:
        supervisor_path().unlink()
    except OSError:
        pass
