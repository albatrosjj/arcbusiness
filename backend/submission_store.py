"""JSON-file store for milestone work submissions (Step 4 of the workflow).

The deployed ArcBusiness contract has no submit() function, so deliverables
live off-chain in submissions.json; the milestone's on-chain status stays
Funded and the UI overlays "Submitted" when a submission exists. Same
JSON-file approach as listing_store / user_store.
"""

import json
import threading
import time
from pathlib import Path

STORE_PATH = Path(__file__).resolve().parent.parent / "submissions.json"

_lock = threading.Lock()


def _load() -> dict:
    if STORE_PATH.exists():
        return json.loads(STORE_PATH.read_text())
    return {"submissions": []}


def _save(data: dict) -> None:
    STORE_PATH.write_text(json.dumps(data, indent=2))


def add_submission(agreement_id: int, milestone_id: int, description: str,
                   url: str | None, email: str, wallet_address: str) -> dict:
    with _lock:
        data = _load()
        submission = {
            "agreement_id": agreement_id,
            "milestone_id": milestone_id,
            "description": description,
            "url": url or None,
            "provider_email": email,
            "provider_address": wallet_address,
            "submitted_at": int(time.time()),
        }
        data["submissions"].append(submission)
        _save(data)
    return submission


def list_for_agreement(agreement_id: int) -> list[dict]:
    return [s for s in _load()["submissions"] if s["agreement_id"] == agreement_id]


def get_submission(agreement_id: int, milestone_id: int) -> dict | None:
    """Latest submission for a milestone, if any."""
    matches = [s for s in list_for_agreement(agreement_id) if s["milestone_id"] == milestone_id]
    return matches[-1] if matches else None
