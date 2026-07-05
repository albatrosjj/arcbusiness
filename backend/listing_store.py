"""Simple JSON-file store for open job listings.

A listing is an agreement without a provider yet. Providers apply with their
wallet address; when the client accepts one, the onchain agreement is created
and the listing is marked filled. Same JSON-file approach as user_store.
"""

import json
import threading
import time
from pathlib import Path

STORE_PATH = Path(__file__).resolve().parent.parent / "listings.json"

_lock = threading.Lock()


def _load() -> dict:
    if STORE_PATH.exists():
        return json.loads(STORE_PATH.read_text())
    return {"listings": [], "next_id": 0}


def _save(data: dict) -> None:
    STORE_PATH.write_text(json.dumps(data, indent=2))


def create_listing(title: str, description: str, budget: float, deadline: int,
                   client_email: str | None, client_address: str | None) -> dict:
    with _lock:
        data = _load()
        listing = {
            "listing_id": data["next_id"],
            "title": title,
            "description": description,
            "budget": budget,
            "deadline": deadline,
            "client_email": client_email,
            "client_address": client_address,
            "created_at": int(time.time()),
            "status": "open",  # open | filled
            "applications": [],  # {email, wallet_address, applied_at}
            "agreement_id": None,
        }
        data["listings"].append(listing)
        data["next_id"] += 1
        _save(data)
    return listing


def list_listings() -> list[dict]:
    return _load()["listings"]


def get_listing(listing_id: int) -> dict | None:
    for l in _load()["listings"]:
        if l["listing_id"] == listing_id:
            return l
    return None


def add_application(listing_id: int, email: str, wallet_address: str) -> dict:
    """Add an application; raises ValueError if not possible."""
    with _lock:
        data = _load()
        listing = next((l for l in data["listings"] if l["listing_id"] == listing_id), None)
        if listing is None:
            raise ValueError("listing not found")
        if listing["status"] != "open":
            raise ValueError("listing is no longer open")
        if any(a["wallet_address"].lower() == wallet_address.lower() for a in listing["applications"]):
            raise ValueError("you already applied to this job")
        listing["applications"].append(
            {"email": email, "wallet_address": wallet_address, "applied_at": int(time.time())}
        )
        _save(data)
    return listing


def mark_filled(listing_id: int, agreement_id: int | None) -> dict:
    with _lock:
        data = _load()
        listing = next((l for l in data["listings"] if l["listing_id"] == listing_id), None)
        if listing is None:
            raise ValueError("listing not found")
        listing["status"] = "filled"
        listing["agreement_id"] = agreement_id
        _save(data)
    return listing
