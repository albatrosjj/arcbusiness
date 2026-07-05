"""Simple JSON-file store for users, sessions and login OTPs.

Maps email -> Circle user/wallet, and session token -> email. Good enough for
a testnet demo; swap for SQLite/Postgres in production.
"""

import json
import secrets
import threading
import time
from pathlib import Path

STORE_PATH = Path(__file__).resolve().parent.parent / "users.json"

OTP_TTL = 10 * 60  # seconds
SESSION_TTL = 7 * 24 * 3600

_lock = threading.Lock()


def _load() -> dict:
    if STORE_PATH.exists():
        return json.loads(STORE_PATH.read_text())
    return {"users": {}, "sessions": {}, "otps": {}, "meta": {}}


def _save(data: dict) -> None:
    STORE_PATH.write_text(json.dumps(data, indent=2))


def create_otp(email: str) -> str:
    otp = f"{secrets.randbelow(1_000_000):06d}"
    with _lock:
        data = _load()
        data["otps"][email] = {"otp": otp, "expires": time.time() + OTP_TTL}
        _save(data)
    return otp


def verify_otp(email: str, otp: str) -> bool:
    with _lock:
        data = _load()
        entry = data["otps"].get(email)
        if not entry or entry["expires"] < time.time() or entry["otp"] != otp:
            return False
        del data["otps"][email]
        _save(data)
    return True


def get_user(email: str) -> dict | None:
    return _load()["users"].get(email)


def save_user(email: str, user: dict) -> None:
    with _lock:
        data = _load()
        data["users"][email] = user
        _save(data)


def create_session(email: str) -> str:
    token = secrets.token_urlsafe(32)
    with _lock:
        data = _load()
        data["sessions"][token] = {"email": email, "expires": time.time() + SESSION_TTL}
        _save(data)
    return token


def get_session(token: str) -> dict | None:
    """Return the user dict for a valid session token, else None."""
    data = _load()
    s = data["sessions"].get(token)
    if not s or s["expires"] < time.time():
        return None
    return data["users"].get(s["email"])


def delete_session(token: str) -> None:
    with _lock:
        data = _load()
        data["sessions"].pop(token, None)
        _save(data)


def get_meta(key: str) -> str | None:
    return _load()["meta"].get(key)


def set_meta(key: str, value: str) -> None:
    with _lock:
        data = _load()
        data["meta"][key] = value
        _save(data)
