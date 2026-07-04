"""Compile and deploy ArcBusiness.sol to Arc Testnet.

Usage:
    python scripts/deploy.py

Requires PRIVATE_KEY in .env with testnet USDC for gas
(faucet: https://faucet.circle.com).
"""

import json
import sys
from pathlib import Path

from dotenv import load_dotenv
from eth_account import Account
from solcx import compile_standard, install_solc
from web3 import Web3

import os

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
SOLC_VERSION = "0.8.24"
RPC_URL = os.getenv("RPC_URL", "https://rpc.testnet.arc.network")
CHAIN_ID = int(os.getenv("CHAIN_ID", "5042002"))
EXPLORER = "https://testnet.arcscan.app"


def main():
    private_key = os.getenv("PRIVATE_KEY")
    if not private_key:
        sys.exit("PRIVATE_KEY not set in .env")

    print(f"Installing solc {SOLC_VERSION}...")
    install_solc(SOLC_VERSION)

    source = (ROOT / "contracts" / "ArcBusiness.sol").read_text()
    print("Compiling ArcBusiness.sol...")
    compiled = compile_standard(
        {
            "language": "Solidity",
            "sources": {"ArcBusiness.sol": {"content": source}},
            "settings": {
                "optimizer": {"enabled": True, "runs": 200},
                "outputSelection": {"*": {"*": ["abi", "evm.bytecode.object"]}},
            },
        },
        solc_version=SOLC_VERSION,
    )
    contract = compiled["contracts"]["ArcBusiness.sol"]["ArcBusiness"]
    abi = contract["abi"]
    bytecode = contract["evm"]["bytecode"]["object"]

    artifacts = ROOT / "artifacts"
    artifacts.mkdir(exist_ok=True)
    (artifacts / "ArcBusiness.abi.json").write_text(json.dumps(abi, indent=2))

    w3 = Web3(Web3.HTTPProvider(RPC_URL))
    if not w3.is_connected():
        sys.exit(f"Cannot connect to {RPC_URL}")
    account = Account.from_key(private_key)
    balance = w3.eth.get_balance(account.address)
    print(f"Deployer: {account.address} (native balance: {balance / 10**18:.6f} USDC)")
    if balance == 0:
        sys.exit("Deployer has no USDC for gas — use https://faucet.circle.com")

    factory = w3.eth.contract(abi=abi, bytecode=bytecode)
    tx = factory.constructor().build_transaction(
        {
            "from": account.address,
            "nonce": w3.eth.get_transaction_count(account.address),
            "chainId": CHAIN_ID,
        }
    )
    signed = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    print(f"Deploy tx: {EXPLORER}/tx/{tx_hash.hex()}")
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
    if receipt.status != 1:
        sys.exit("Deployment failed")

    address = receipt.contractAddress
    print(f"\n✅ ArcBusiness deployed: {address}")
    print(f"   {EXPLORER}/address/{address}")
    print(f"\nAdd to .env:\nARCBUSINESS_CONTRACT={address}")


if __name__ == "__main__":
    main()
