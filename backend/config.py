import os

from dotenv import load_dotenv

load_dotenv()

# Arc Testnet
RPC_URL = os.getenv("RPC_URL", "https://rpc.testnet.arc.network")
CHAIN_ID = int(os.getenv("CHAIN_ID", "5042002"))
EXPLORER_URL = os.getenv("EXPLORER_URL", "https://testnet.arcscan.app")
USDC_ADDRESS = "0x3600000000000000000000000000000000000000"
USDC_DECIMALS = 6  # ERC-20 interface uses 6 decimals (native gas token uses 18)

# Deployed ArcBusiness contract (set after deploy)
CONTRACT_ADDRESS = os.getenv("ARCBUSINESS_CONTRACT", "")

# Server-side signer used to submit transactions (demo mode)
PRIVATE_KEY = os.getenv("PRIVATE_KEY", "")

# Circle Developer Controlled Wallets
CIRCLE_API_KEY = os.getenv("CIRCLE_API_KEY", "")
CIRCLE_ENTITY_SECRET = os.getenv("CIRCLE_ENTITY_SECRET", "")
CIRCLE_API_BASE = "https://api.circle.com/v1/w3s"
CIRCLE_BLOCKCHAIN = os.getenv("CIRCLE_BLOCKCHAIN", "ARC-TESTNET")

# Anthropic (optional: AI-drafted agreement/milestone descriptions)
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# ERC-8004 Identity Registry (agent identity for parties); optional
ERC8004_IDENTITY_REGISTRY = os.getenv("ERC8004_IDENTITY_REGISTRY", "")
