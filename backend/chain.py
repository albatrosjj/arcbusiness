"""Web3 helpers for the ArcBusiness contract on Arc Testnet."""

import json
from pathlib import Path

from eth_account import Account
from web3 import Web3

from . import config

ABI_PATH = Path(__file__).resolve().parent.parent / "artifacts" / "ArcBusiness.abi.json"

ERC20_ABI = [
    {
        "type": "function",
        "name": "approve",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "spender", "type": "address"},
            {"name": "amount", "type": "uint256"},
        ],
        "outputs": [{"name": "", "type": "bool"}],
    },
    {
        "type": "function",
        "name": "balanceOf",
        "stateMutability": "view",
        "inputs": [{"name": "account", "type": "address"}],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "type": "function",
        "name": "allowance",
        "stateMutability": "view",
        "inputs": [
            {"name": "owner", "type": "address"},
            {"name": "spender", "type": "address"},
        ],
        "outputs": [{"name": "", "type": "uint256"}],
    },
]

w3 = Web3(Web3.HTTPProvider(config.RPC_URL))


def get_account():
    if not config.PRIVATE_KEY:
        raise RuntimeError("PRIVATE_KEY not set in .env")
    return Account.from_key(config.PRIVATE_KEY)


def load_abi():
    return json.loads(ABI_PATH.read_text())


def get_contract():
    if not config.CONTRACT_ADDRESS:
        raise RuntimeError("ARCBUSINESS_CONTRACT not set in .env — deploy first (scripts/deploy.py)")
    return w3.eth.contract(address=Web3.to_checksum_address(config.CONTRACT_ADDRESS), abi=load_abi())


def get_usdc():
    return w3.eth.contract(address=Web3.to_checksum_address(config.USDC_ADDRESS), abi=ERC20_ABI)


def to_usdc_units(amount: float) -> int:
    return int(round(amount * 10**config.USDC_DECIMALS))


def from_usdc_units(units: int) -> float:
    return units / 10**config.USDC_DECIMALS


def tx_link(tx_hash: str) -> str:
    return f"{config.EXPLORER_URL}/tx/{tx_hash}"


def send_tx(fn, account, value: int = 0):
    """Build, sign and send a contract function call. Returns the tx hash (hex str)."""
    tx = fn.build_transaction(
        {
            "from": account.address,
            "nonce": w3.eth.get_transaction_count(account.address),
            "chainId": config.CHAIN_ID,
            "value": value,
        }
    )
    signed = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    return tx_hash.hex() if tx_hash.hex().startswith("0x") else "0x" + tx_hash.hex()


def wait_receipt(tx_hash: str, timeout: int = 120):
    return w3.eth.wait_for_transaction_receipt(tx_hash, timeout=timeout)
