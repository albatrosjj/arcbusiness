"""ArcBusiness — 'Stripe for Agreements' on Arc Blockchain.

FastAPI backend exposing the ArcBusiness contract as REST endpoints, with
Circle Developer Controlled Wallets, ERC-8004 agent identity, and streaming
transaction status.
"""

import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field
from web3 import Web3

from . import chain, circle_wallets, config, erc8004

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


class RegisterAgentReq(BaseModel):
    agent_domain: str
    agent_address: str


class CircleWalletReq(BaseModel):
    wallet_set_id: str
    ref_id: str = ""


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


def _call_and_wait(fn, extra: dict | None = None) -> dict:
    account = chain.get_account()
    try:
        tx_hash = chain.send_tx(fn, account)
        receipt = chain.wait_receipt(tx_hash)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _tx_response(tx_hash, receipt, extra)


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


# ---------- Agreements ----------

@app.post("/api/agreements")
async def create_agreement(req: CreateAgreementReq):
    contract = chain.get_contract()
    fn = contract.functions.createAgreement(
        Web3.to_checksum_address(req.party2),
        req.title,
        chain.to_usdc_units(req.total_amount),
    )
    result = _call_and_wait(fn)
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
        milestones.append(
            {
                "milestone_id": mid,
                "description": m[0],
                "amount": chain.from_usdc_units(m[1]),
                "deadline": m[2],
                "disputed_at": m[3],
                "status": MILESTONE_STATUS[m[4]],
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


# ---------- Milestones ----------

@app.post("/api/milestones")
async def create_milestone(req: CreateMilestoneReq):
    contract = chain.get_contract()
    fn = contract.functions.createMilestone(
        req.agreement_id, req.description, chain.to_usdc_units(req.amount), req.deadline
    )
    return _call_and_wait(fn)


@app.post("/api/milestones/lock")
async def lock_usdc(req: MilestoneRef):
    contract = chain.get_contract()
    usdc = chain.get_usdc()
    account = chain.get_account()

    m = contract.functions.getMilestone(req.agreement_id, req.milestone_id).call()
    amount = m[1]

    # Ensure allowance covers the escrow amount
    allowance = usdc.functions.allowance(account.address, contract.address).call()
    approve_result = None
    if allowance < amount:
        approve_hash = chain.send_tx(usdc.functions.approve(contract.address, amount), account)
        approve_receipt = chain.wait_receipt(approve_hash)
        approve_result = _tx_response(approve_hash, approve_receipt)

    result = _call_and_wait(contract.functions.lockUSDC(req.agreement_id, req.milestone_id))
    result["approve"] = approve_result
    return result


@app.post("/api/milestones/release")
async def release_payment(req: MilestoneRef):
    contract = chain.get_contract()
    return _call_and_wait(contract.functions.releasePayment(req.agreement_id, req.milestone_id))


@app.post("/api/milestones/dispute")
async def open_dispute(req: MilestoneRef):
    contract = chain.get_contract()
    return _call_and_wait(contract.functions.openDispute(req.agreement_id, req.milestone_id))


@app.post("/api/milestones/refund")
async def claim_refund(req: MilestoneRef):
    """Refund a disputed milestone after the 48h window."""
    contract = chain.get_contract()
    return _call_and_wait(contract.functions.claimRefund(req.agreement_id, req.milestone_id))


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
