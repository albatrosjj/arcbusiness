# ArcBusiness

**Stripe for Agreements — milestone-based USDC escrow on the Arc Blockchain.**

ArcBusiness lets a **Client** and a **Service Provider** formalize work agreements on-chain, fund milestones with USDC held in escrow, and release payments instantly as work is delivered — with a built-in dispute path when things go wrong.

- **Live contract (Arc Testnet):** [`0x57a716942b728cb1768B90B6Fb00a4833A87B17c`](https://testnet.arcscan.app/address/0x57a716942b728cb1768B90B6Fb00a4833A87B17c)

## What It Is

Traditional freelance and service payments rely on trust or slow, expensive intermediaries. ArcBusiness replaces both with a smart-contract escrow:

1. A client and provider agree on scoped **milestones**, each with a USDC value.
2. The client **locks USDC** into the contract per milestone.
3. On delivery, the client **releases payment** — funds settle to the provider in under a second.
4. If there's a disagreement, either party can **open a dispute**; a disputed milestone auto-refunds to the client after 48 hours, or can be resolved sooner by either party.

## How It Works

Core contract functions (`contracts/ArcBusiness.sol`, Solidity 0.8.24):

| Function | Caller | Description |
|---|---|---|
| `createAgreement` | Client | Creates an agreement between client and provider |
| `createMilestone` | Either party | Adds a milestone with a USDC amount to an agreement |
| `lockUSDC` | Client | Escrows USDC for a milestone (`approve` + `transferFrom`) |
| `releasePayment` | Client | Releases escrowed USDC to the provider |
| `openDispute` | Either party | Flags a milestone as disputed; starts the 48h refund window |

Dispute resolution: the provider can refund immediately (`resolveDisputeRefund`), the client can release despite the dispute (`resolveDisputeRelease`), or after 48 hours anyone can call `claimRefund` to return funds to the client.

## Why Arc

- **0.48s finality** — releasing a milestone feels like a card swipe, not a blockchain wait.
- **USDC-native** — USDC is Arc's native asset (ERC-20 at `0x3600000000000000000000000000000000000000`, 6 decimals) and is also used for gas. No bridging or wrapped tokens.
- **ERC-8004 agent identity** — clients and providers register verifiable on-chain agent identities, enabling trustless counterparty discovery.

## Architecture

```
contracts/ArcBusiness.sol   Escrow contract (USDC, 6 decimals)
scripts/deploy.py           Compile (solc 0.8.24) + deploy to Arc Testnet
backend/                    FastAPI: REST endpoints, Circle wallets, ERC-8004, SSE tx streams
templates/index.html        Dark-theme web UI (Client / Service Provider roles)
```

## Tech Stack

- **Smart contract:** Solidity 0.8.24 on Arc Testnet
- **Backend:** Python + FastAPI (REST API, server-sent-event transaction streams)
- **Chain access:** Web3.py
- **Wallets:** Circle Developer Controlled Wallets

## Getting Started

### Prerequisites

- Python 3.11+
- Circle API credentials (for developer-controlled wallets)
- Testnet USDC for the deployer address (used for gas on Arc): https://faucet.circle.com

### Setup

```bash
git clone <this-repo> && cd arcbusiness

python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in PRIVATE_KEY, CIRCLE_API_KEY, CIRCLE_ENTITY_SECRET, ANTHROPIC_API_KEY
```

### Deploy (optional — a live contract already exists)

```bash
python scripts/deploy.py
# copy the printed address into .env as ARCBUSINESS_CONTRACT=0x…
```

Or use the deployed testnet contract: `ARCBUSINESS_CONTRACT=0x57a716942b728cb1768B90B6Fb00a4833A87B17c`

### Run

```bash
uvicorn backend.main:app --reload
# open http://localhost:8000
```

## API Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/health` | Health check |
| `POST` | `/api/agreements` | `createAgreement(party2, title, totalAmount)` |
| `GET` | `/api/agreements`, `/api/agreements/{id}` | List / detail (with milestones + ERC-8004 identities) |
| `POST` | `/api/milestones` | `createMilestone` |
| `POST` | `/api/milestones/lock` | `approve` + `lockUSDC` (escrow) |
| `POST` | `/api/milestones/release` | `releasePayment` |
| `POST` | `/api/milestones/dispute` | `openDispute` |
| `POST` | `/api/milestones/refund` | `claimRefund` (after 48h dispute window) |
| `GET` | `/api/tx/{hash}/stream` | SSE stream of tx confirmation status |
| `POST` | `/api/agents/register` | Register ERC-8004 agent identity |
| `GET` | `/api/agents/{address}` | Look up an agent |
| `POST`/`GET` | `/api/circle/...` | Circle wallet sets, wallets, balances |

## Network

| | |
|---|---|
| Chain ID | 5042002 |
| RPC | https://rpc.testnet.arc.network |
| Explorer | https://testnet.arcscan.app |
| USDC (ERC-20) | `0x3600000000000000000000000000000000000000` (6 decimals) |

> Note: Arc's native gas token is USDC with 18 decimals internally; the ERC-20 interface used by this contract is 6 decimals. Never mix the two.

## Notes

- The backend signs transactions with `PRIVATE_KEY` (demo mode: one server signer plays whichever role is acting). For production, route calls through Circle developer-controlled wallets (`/api/circle/...` + `circle_wallets.contract_execution`) so each party has its own wallet.
- If `ERC8004_IDENTITY_REGISTRY` is unset, agent identity uses an in-memory fallback registry.

## Author

Built by [@Albatros_0x](https://twitter.com/Albatros_0x)

## License

MIT
