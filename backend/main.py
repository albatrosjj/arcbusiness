"""ArcBusiness — 'Stripe for Agreements' on Arc Blockchain.

FastAPI backend exposing the ArcBusiness contract as REST endpoints, with
Circle Developer Controlled Wallets, ERC-8004 agent identity, and streaming
transaction status.
"""

import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field
from web3 import Web3

from . import auth, chain, circle_wallets, config, erc8004, listing_store, submission_store, user_store

app = FastAPI(title="ArcBusiness", description="Stripe for Agreements on Arc", version="1.0.0")

TEMPLATES = Path(__file__).resolve().parent.parent / "templates"

MILESTONE_STATUS = ["Created", "Funded", "Released", "Disputed", "Refunded"]


# ---------- Models ----------

class CreateAgreementReq(BaseModel):
    party2: str = Field(..., description="Service provider address")
    title: str
    total_amount: float = Field(..., gt=0, description="Total USDC amount")


class CreateMilestoneReq(BaseModel):
    agreement_id: int
    description: str
    amount: float = Field(..., gt=0, description="USDC amount")
    deadline: int = Field(..., description="Unix timestamp")


class MilestoneRef(BaseModel):
    agreement_id: int
    milestone_id: int


class SubmitWorkReq(BaseModel):
    agreement_id: int
    milestone_id: int
    description: str = Field(..., min_length=1)
    url: str | None = None


class CreateListingReq(BaseModel):
    title: str
    description: str
    budget: float = Field(..., gt=0, description="Budget in USDC")
    deadline: int = Field(..., description="Unix timestamp")


class RegisterAgentReq(BaseModel):
    agent_domain: str
    agent_address: str


class CircleWalletReq(BaseModel):
    wallet_set_id: str
    ref_id: str = ""


class RequestOtpReq(BaseModel):
    email: str = Field(..., pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class VerifyOtpReq(BaseModel):
    email: str = Field(..., pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    otp: str


# ---------- Helpers ----------

def _tx_response(tx_hash: str, receipt, extra: dict | None = None) -> dict:
    out = {
        "tx_hash": tx_hash,
        "tx_link": chain.tx_link(tx_hash),
        "status": "confirmed" if receipt.status == 1 else "failed",
        "block": receipt.blockNumber,
        "gas_used": receipt.gasUsed,
    }
    if extra:
        out.update(extra)
    return out


def _current_user(authorization: str | None) -> dict | None:
    """Resolve the logged-in user from a Bearer session token, if any."""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    return user_store.get_session(authorization.removeprefix("Bearer "))


def _require_user(authorization: str | None) -> dict:
    """401 unless a valid session is presented. All write actions require login."""
    user = _current_user(authorization)
    if not user:
        raise HTTPException(status_code=401, detail="Sign in to perform this action")
    if not user.get("wallet_id") or not user.get("wallet_address"):
        raise HTTPException(status_code=400, detail="Your account has no signing wallet — sign in again to provision one")
    return user


async def _circle_call(user: dict, contract_address: str, abi_sig: str, params: list,
                       extra: dict | None = None) -> dict:
    """Execute a contract call from the user's Circle wallet and wait on-chain."""
    circle_params = [str(p) if isinstance(p, int) and not isinstance(p, bool) else p for p in params]
    try:
        res = await circle_wallets.contract_execution(user["wallet_id"], contract_address, abi_sig, circle_params)
    except circle_wallets.CircleError as e:
        raise HTTPException(status_code=400, detail=str(e))
    tx_id = res.get("id")
    tx_hash = None
    for _ in range(60):
        data = await circle_wallets.get_transaction(tx_id)
        tx = data.get("transaction", {})
        if tx.get("state") in ("FAILED", "CANCELLED", "DENIED"):
            raise HTTPException(status_code=400, detail=f"Circle transaction {tx.get('state')}: {tx.get('errorReason') or ''}")
        if tx.get("txHash"):
            tx_hash = tx["txHash"]
            break
        await asyncio.sleep(2)
    if not tx_hash:
        raise HTTPException(status_code=504, detail="Timed out waiting for Circle transaction hash")
    try:
        receipt = chain.wait_receipt(tx_hash)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    out = _tx_response(tx_hash, receipt, extra)
    out["circle_tx_id"] = tx_id
    out["wallet"] = user["wallet_address"]
    return out


async def _contract_call(user: dict, fn_name: str, abi_sig: str, params: list,
                         extra: dict | None = None) -> dict:
    """Execute a contract call through the logged-in user's Circle wallet."""
    contract = chain.get_contract()
    return await _circle_call(user, contract.address, abi_sig, params, extra)


# ---------- UI ----------

@app.get("/", response_class=HTMLResponse)
async def index():
    return (TEMPLATES / "index.html").read_text()


@app.get("/api/health")
async def health():
    return {
        "ok": True,
        "chain_id": config.CHAIN_ID,
        "rpc": config.RPC_URL,
        "explorer": config.EXPLORER_URL,
        "usdc": config.USDC_ADDRESS,
        "contract": config.CONTRACT_ADDRESS or None,
        "connected": chain.w3.is_connected(),
    }


# ---------- Auth (Circle User Controlled Wallets) ----------

@app.post("/api/auth/request-otp")
async def request_otp(req: RequestOtpReq):
    email = req.email.lower()
    otp = user_store.create_otp(email)
    # No email service on testnet: surface the OTP in the server console and
    # return it so the demo is self-contained. Remove `dev_otp` in production.
    print(f"[auth] OTP for {email}: {otp}")
    return {"ok": True, "email": email, "dev_otp": otp}


@app.post("/api/auth/verify")
async def verify_otp(req: VerifyOtpReq):
    email = req.email.lower()
    if not user_store.verify_otp(email, req.otp.strip()):
        raise HTTPException(status_code=401, detail="Invalid or expired code")
    try:
        user = await auth.provision_wallet(email)
    except circle_wallets.CircleError as e:
        raise HTTPException(status_code=502, detail=f"Wallet provisioning failed: {e}")
    token = user_store.create_session(email)
    return {"token": token, "user": _public_user(user)}


@app.get("/api/auth/me")
async def me(authorization: str | None = Header(None)):
    user = _current_user(authorization)
    if not user:
        raise HTTPException(status_code=401, detail="Not logged in")
    return _public_user(user)


@app.post("/api/auth/logout")
async def logout(authorization: str | None = Header(None)):
    if authorization and authorization.startswith("Bearer "):
        user_store.delete_session(authorization.removeprefix("Bearer "))
    return {"ok": True}


def _public_user(user: dict) -> dict:
    out = {
        "email": user["email"],
        "wallet_address": user.get("wallet_address"),
        "wallet_type": user.get("wallet_type"),
    }
    try:
        balance = chain.get_usdc().functions.balanceOf(
            Web3.to_checksum_address(user["wallet_address"])
        ).call()
        out["usdc_balance"] = chain.from_usdc_units(balance)
    except Exception:
        out["usdc_balance"] = None
    return out


# ---------- Agreements ----------

@app.post("/api/agreements")
async def create_agreement(req: CreateAgreementReq, authorization: str | None = Header(None)):
    user = _require_user(authorization)
    contract = chain.get_contract()
    result = await _contract_call(
        user,
        "createAgreement",
        "createAgreement(address,string,uint256)",
        [Web3.to_checksum_address(req.party2), req.title, chain.to_usdc_units(req.total_amount)],
    )
    # Recover agreementId from the AgreementCreated event
    receipt = chain.wait_receipt(result["tx_hash"])
    logs = contract.events.AgreementCreated().process_receipt(receipt)
    if logs:
        result["agreement_id"] = logs[0]["args"]["agreementId"]
    return result


@app.get("/api/agreements/{agreement_id}")
async def get_agreement(agreement_id: int):
    contract = chain.get_contract()
    a = contract.functions.getAgreement(agreement_id).call()
    if a[0] == "0x0000000000000000000000000000000000000000":
        raise HTTPException(status_code=404, detail="agreement not found")
    milestones = []
    for mid in range(a[5]):
        m = contract.functions.getMilestone(agreement_id, mid).call()
        status = MILESTONE_STATUS[m[4]]
        submission = submission_store.get_submission(agreement_id, mid)
        # The contract has no Submitted state; overlay it when a funded
        # milestone has an off-chain deliverable awaiting client review.
        if status == "Funded" and submission:
            status = "Submitted"
        milestones.append(
            {
                "milestone_id": mid,
                "description": m[0],
                "amount": chain.from_usdc_units(m[1]),
                "deadline": m[2],
                "disputed_at": m[3],
                "status": status,
                "submission": submission,
                "refundable": contract.functions.isRefundable(agreement_id, mid).call(),
            }
        )
    return {
        "agreement_id": agreement_id,
        "client": a[0],
        "provider": a[1],
        "title": a[2],
        "total_amount": chain.from_usdc_units(a[3]),
        "created_at": a[4],
        "active": a[6],
        "milestones": milestones,
        "client_identity": erc8004.resolve_agent(a[0]),
        "provider_identity": erc8004.resolve_agent(a[1]),
    }


@app.get("/api/agreements")
async def list_agreements():
    contract = chain.get_contract()
    count = contract.functions.agreementCount().call()
    out = []
    for aid in range(count):
        a = contract.functions.getAgreement(aid).call()
        out.append(
            {
                "agreement_id": aid,
                "client": a[0],
                "provider": a[1],
                "title": a[2],
                "total_amount": chain.from_usdc_units(a[3]),
                "created_at": a[4],
                "milestone_count": a[5],
                "active": a[6],
            }
        )
    return {"count": count, "agreements": out}


# ---------- Job listings (open agreements without a provider) ----------

class AcceptApplicationReq(BaseModel):
    wallet_address: str = Field(..., description="Applicant wallet address to accept")


def _listing_owner(listing: dict, user: dict) -> bool:
    return bool(listing["client_email"]) and user["email"] == listing["client_email"]


@app.post("/api/listings")
async def create_listing(req: CreateListingReq, authorization: str | None = Header(None)):
    user = _require_user(authorization)
    return listing_store.create_listing(
        req.title, req.description, req.budget, req.deadline,
        user["email"], user["wallet_address"],
    )


@app.get("/api/listings")
async def list_listings():
    listings = listing_store.list_listings()
    return {
        "count": len(listings),
        "listings": [
            {**l, "applicant_count": len(l["applications"])}
            for l in listings
        ],
    }


@app.post("/api/listings/{listing_id}/apply")
async def apply_to_listing(listing_id: int, authorization: str | None = Header(None)):
    user = _require_user(authorization)
    listing = listing_store.get_listing(listing_id)
    if listing is None:
        raise HTTPException(status_code=404, detail="listing not found")
    if listing["client_email"] and listing["client_email"] == user["email"]:
        raise HTTPException(status_code=400, detail="You cannot apply to your own listing")
    try:
        listing = listing_store.add_application(listing_id, user["email"], user["wallet_address"])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {**listing, "applicant_count": len(listing["applications"])}


@app.post("/api/listings/{listing_id}/accept")
async def accept_application(listing_id: int, req: AcceptApplicationReq,
                             authorization: str | None = Header(None)):
    user = _require_user(authorization)
    listing = listing_store.get_listing(listing_id)
    if listing is None:
        raise HTTPException(status_code=404, detail="listing not found")
    if listing["status"] != "open":
        raise HTTPException(status_code=400, detail="listing is no longer open")
    if not _listing_owner(listing, user):
        raise HTTPException(status_code=403, detail="Only the listing owner can accept applications")
    provider = Web3.to_checksum_address(req.wallet_address)
    if not any(a["wallet_address"].lower() == provider.lower() for a in listing["applications"]):
        raise HTTPException(status_code=400, detail="that address has not applied to this listing")

    # Create the onchain agreement with the accepted provider; escrow flow
    # (milestones, lockUSDC, release) continues as usual from here.
    contract = chain.get_contract()
    result = await _contract_call(
        user,
        "createAgreement",
        "createAgreement(address,string,uint256)",
        [provider, listing["title"], chain.to_usdc_units(listing["budget"])],
    )
    receipt = chain.wait_receipt(result["tx_hash"])
    logs = contract.events.AgreementCreated().process_receipt(receipt)
    agreement_id = logs[0]["args"]["agreementId"] if logs else None
    result["agreement_id"] = agreement_id
    result["listing"] = listing_store.mark_filled(listing_id, agreement_id)
    return result


def _require_party(user: dict, agreement_id: int, roles: tuple[str, ...]) -> None:
    """403 unless the logged-in user's wallet is one of the allowed agreement parties."""
    a = chain.get_contract().functions.getAgreement(agreement_id).call()
    allowed = {a[0].lower() for r in roles if r == "client"} | {a[1].lower() for r in roles if r == "provider"}
    if user["wallet_address"].lower() not in allowed:
        raise HTTPException(status_code=403, detail=f"Only the agreement {' or '.join(roles)} can perform this action")


# ---------- Milestones ----------

async def _lock_milestone(user: dict, agreement_id: int, milestone_id: int) -> dict:
    """Approve (if needed) and lock the milestone's USDC in escrow."""
    contract = chain.get_contract()
    usdc = chain.get_usdc()
    m = contract.functions.getMilestone(agreement_id, milestone_id).call()
    amount = m[1]

    allowance = usdc.functions.allowance(
        Web3.to_checksum_address(user["wallet_address"]), contract.address
    ).call()
    approve_result = None
    if allowance < amount:
        approve_result = await _circle_call(
            user, usdc.address, "approve(address,uint256)", [contract.address, amount]
        )

    result = await _contract_call(
        user, "lockUSDC", "lockUSDC(uint256,uint256)", [agreement_id, milestone_id]
    )
    result["approve"] = approve_result
    return result


@app.post("/api/milestones")
async def create_and_fund_milestone(req: CreateMilestoneReq, authorization: str | None = Header(None)):
    """Step 2: client adds a milestone and its USDC is locked in escrow in one step."""
    user = _require_user(authorization)
    _require_party(user, req.agreement_id, ("client",))
    contract = chain.get_contract()
    result = await _contract_call(
        user,
        "createMilestone",
        "createMilestone(uint256,string,uint256,uint256)",
        [req.agreement_id, req.description, chain.to_usdc_units(req.amount), req.deadline],
    )
    receipt = chain.wait_receipt(result["tx_hash"])
    logs = contract.events.MilestoneCreated().process_receipt(receipt)
    if not logs:
        raise HTTPException(status_code=500, detail="Milestone created but its id could not be recovered from the event log")
    milestone_id = logs[0]["args"]["milestoneId"]
    result["milestone_id"] = milestone_id

    lock = await _lock_milestone(user, req.agreement_id, milestone_id)
    result["lock"] = lock
    return result


@app.post("/api/milestones/lock")
async def lock_usdc(req: MilestoneRef, authorization: str | None = Header(None)):
    """Retry escrow funding for a milestone that was created but not locked."""
    user = _require_user(authorization)
    _require_party(user, req.agreement_id, ("client",))
    return await _lock_milestone(user, req.agreement_id, req.milestone_id)


@app.post("/api/milestones/submit")
async def submit_work(req: SubmitWorkReq, authorization: str | None = Header(None)):
    """Step 4: provider submits the deliverable for a funded milestone."""
    user = _require_user(authorization)
    _require_party(user, req.agreement_id, ("provider",))
    contract = chain.get_contract()
    m = contract.functions.getMilestone(req.agreement_id, req.milestone_id).call()
    if MILESTONE_STATUS[m[4]] != "Funded":
        raise HTTPException(status_code=400, detail="Milestone must be funded (USDC locked) before submitting work")
    if submission_store.get_submission(req.agreement_id, req.milestone_id):
        raise HTTPException(status_code=400, detail="Work already submitted for this milestone")

    # The deployed contract predates submitWork(); call it when the ABI has it,
    # otherwise the submission is recorded off-chain only.
    result: dict = {"status": "submitted", "on_chain": False}
    if any(f.get("name") == "submitWork" for f in chain.load_abi() if f.get("type") == "function"):
        result = await _contract_call(
            user, "submitWork", "submitWork(uint256,uint256)", [req.agreement_id, req.milestone_id]
        )
        result["on_chain"] = True

    result["submission"] = submission_store.add_submission(
        req.agreement_id, req.milestone_id, req.description.strip(),
        (req.url or "").strip() or None, user["email"], user["wallet_address"],
    )
    return result


@app.get("/api/agreements/{agreement_id}/submissions")
async def list_submissions(agreement_id: int):
    return {"agreement_id": agreement_id, "submissions": submission_store.list_for_agreement(agreement_id)}


@app.post("/api/milestones/release")
async def release_payment(req: MilestoneRef, authorization: str | None = Header(None)):
    user = _require_user(authorization)
    _require_party(user, req.agreement_id, ("client",))
    return await _contract_call(
        user,
        "releasePayment", "releasePayment(uint256,uint256)",
        [req.agreement_id, req.milestone_id],
    )


@app.post("/api/milestones/dispute")
async def open_dispute(req: MilestoneRef, authorization: str | None = Header(None)):
    user = _require_user(authorization)
    _require_party(user, req.agreement_id, ("client", "provider"))
    return await _contract_call(
        user,
        "openDispute", "openDispute(uint256,uint256)",
        [req.agreement_id, req.milestone_id],
    )


@app.post("/api/milestones/refund")
async def claim_refund(req: MilestoneRef, authorization: str | None = Header(None)):
    """Refund a disputed milestone after the 48h window."""
    user = _require_user(authorization)
    _require_party(user, req.agreement_id, ("client",))
    return await _contract_call(
        user,
        "claimRefund", "claimRefund(uint256,uint256)",
        [req.agreement_id, req.milestone_id],
    )


# ---------- Streaming transaction status ----------

@app.get("/api/tx/{tx_hash}/stream")
async def stream_tx_status(tx_hash: str):
    """Server-sent events stream of a transaction's confirmation status."""

    async def event_stream():
        yield f"data: {json.dumps({'stage': 'pending', 'tx_hash': tx_hash, 'tx_link': chain.tx_link(tx_hash)})}\n\n"
        for _ in range(120):
            try:
                receipt = chain.w3.eth.get_transaction_receipt(tx_hash)
            except Exception:
                receipt = None
            if receipt is not None:
                confirmations = chain.w3.eth.block_number - receipt.blockNumber + 1
                payload = {
                    "stage": "confirmed" if receipt.status == 1 else "failed",
                    "block": receipt.blockNumber,
                    "confirmations": confirmations,
                    "gas_used": receipt.gasUsed,
                    "tx_link": chain.tx_link(tx_hash),
                }
                yield f"data: {json.dumps(payload)}\n\n"
                return
            await asyncio.sleep(1)
        yield f"data: {json.dumps({'stage': 'timeout', 'tx_hash': tx_hash})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ---------- ERC-8004 agent identity ----------

@app.post("/api/agents/register")
async def register_agent(req: RegisterAgentReq):
    try:
        return erc8004.register_agent(req.agent_domain, req.agent_address)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/agents/{address}")
async def resolve_agent(address: str):
    identity = erc8004.resolve_agent(address)
    if identity is None:
        raise HTTPException(status_code=404, detail="agent not registered")
    return identity


# ---------- Circle Developer Controlled Wallets ----------

@app.post("/api/circle/wallet-sets")
async def create_wallet_set(name: str = "arcbusiness"):
    try:
        return await circle_wallets.create_wallet_set(name)
    except circle_wallets.CircleError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/circle/wallets")
async def create_circle_wallet(req: CircleWalletReq):
    try:
        return await circle_wallets.create_wallet(req.wallet_set_id, req.ref_id)
    except circle_wallets.CircleError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/circle/wallets")
async def list_circle_wallets(wallet_set_id: str | None = None):
    try:
        return await circle_wallets.list_wallets(wallet_set_id)
    except circle_wallets.CircleError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/circle/wallets/{wallet_id}/balances")
async def circle_wallet_balances(wallet_id: str):
    try:
        return await circle_wallets.get_wallet_balance(wallet_id)
    except circle_wallets.CircleError as e:
        raise HTTPException(status_code=400, detail=str(e))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
