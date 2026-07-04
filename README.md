# ArcBusiness — "Stripe for Agreements" on Arc

Milestone-based USDC escrow between a **Client** and a **Service Provider** on
Arc Testnet, with Circle Developer Controlled Wallets, ERC-8004 agent identity,
and a FastAPI backend + web UI.

## Architecture

```
contracts/ArcBusiness.sol   Escrow contract (USDC 0x3600…0000, 6 decimals)
scripts/deploy.py           Compile (solc 0.8.24) + deploy to Arc Testnet
backend/                    FastAPI: REST endpoints, Circle wallets, ERC-8004, SSE tx streams
templates/index.html        Dark-theme UI (Client / Service Provider roles)
```

**Flow:** client creates agreement → parties add milestones → client `lockUSDC`
(escrow via `approve` + `transferFrom`) → client `releasePayment` to provider,
or either party `openDispute`. A disputed milestone auto-refunds to the client:
after 48 hours anyone can call `claimRefund`. The provider can also refund
immediately (`resolveDisputeRefund`) or the client can release despite the
dispute (`resolveDisputeRelease`).

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in PRIVATE_KEY, CIRCLE_API_KEY, CIRCLE_ENTITY_SECRET, ANTHROPIC_API_KEY
```

Fund the deployer address with testnet USDC (used for gas on Arc):
https://faucet.circle.com

## Deploy

```bash
python scripts/deploy.py
# copy the printed address into .env as ARCBUSINESS_CONTRACT=0x…
```

## Run

```bash
uvicorn backend.main:app --reload
# open http://localhost:8000
```

## Network

| | |
|---|---|
| Chain ID | 5042002 |
| RPC | https://rpc.testnet.arc.network |
| Explorer | https://testnet.arcscan.app |
| USDC (ERC-20) | `0x3600000000000000000000000000000000000000` (6 decimals) |

Note: Arc's native gas token is USDC with 18 decimals internally; the ERC-20
interface used by this contract is 6 decimals. Never mix the two.

## API

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/agreements` | createAgreement(party2, title, totalAmount) |
| GET | `/api/agreements` / `/api/agreements/{id}` | list / detail (with milestones + ERC-8004 identities) |
| POST | `/api/milestones` | createMilestone |
| POST | `/api/milestones/lock` | approve + lockUSDC (escrow) |
| POST | `/api/milestones/release` | releasePayment |
| POST | `/api/milestones/dispute` | openDispute |
| POST | `/api/milestones/refund` | claimRefund (after 48h dispute window) |
| GET | `/api/tx/{hash}/stream` | SSE stream of tx confirmation status |
| POST | `/api/agents/register`, GET `/api/agents/{addr}` | ERC-8004 agent identity |
| POST/GET | `/api/circle/...` | Circle wallet sets, wallets, balances |

## Notes

- The backend signs transactions with `PRIVATE_KEY` (demo mode: one server
  signer plays whichever role is acting). For production, route calls through
  Circle developer-controlled wallets (`/api/circle/...` +
  `circle_wallets.contract_execution`) so each party has its own wallet.
- If `ERC8004_IDENTITY_REGISTRY` is unset, agent identity uses an in-memory
  fallback registry.
