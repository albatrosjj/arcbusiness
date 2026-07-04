"""Circle Developer Controlled Wallets integration.

Uses the Circle W3S REST API directly (https://developers.circle.com/w3s).
The entity secret is encrypted with Circle's public key per request, as
required for developer-controlled wallet operations.
"""

import base64
import uuid

import httpx

from . import config

try:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    _HAS_CRYPTO = True
except ImportError:  # pragma: no cover
    _HAS_CRYPTO = False


class CircleError(RuntimeError):
    pass


def _headers() -> dict:
    if not config.CIRCLE_API_KEY:
        raise CircleError("CIRCLE_API_KEY not set in .env")
    return {
        "Authorization": f"Bearer {config.CIRCLE_API_KEY}",
        "Content-Type": "application/json",
    }


async def _get(client: httpx.AsyncClient, path: str, params: dict | None = None) -> dict:
    r = await client.get(f"{config.CIRCLE_API_BASE}{path}", headers=_headers(), params=params)
    if r.status_code >= 400:
        raise CircleError(f"Circle API {r.status_code}: {r.text}")
    return r.json().get("data", {})


async def _post(client: httpx.AsyncClient, path: str, body: dict) -> dict:
    r = await client.post(f"{config.CIRCLE_API_BASE}{path}", headers=_headers(), json=body)
    if r.status_code >= 400:
        raise CircleError(f"Circle API {r.status_code}: {r.text}")
    return r.json().get("data", {})


async def get_entity_secret_ciphertext(client: httpx.AsyncClient) -> str:
    """Encrypt the entity secret with Circle's RSA public key (fresh per request)."""
    if not _HAS_CRYPTO:
        raise CircleError("Install 'cryptography' to use developer-controlled wallets")
    if not config.CIRCLE_ENTITY_SECRET:
        raise CircleError("CIRCLE_ENTITY_SECRET not set in .env")

    data = await _get(client, "/config/entity/publicKey")
    public_key = serialization.load_pem_public_key(data["publicKey"].encode())
    ciphertext = public_key.encrypt(
        bytes.fromhex(config.CIRCLE_ENTITY_SECRET),
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    return base64.b64encode(ciphertext).decode()


async def create_wallet_set(name: str) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        ciphertext = await get_entity_secret_ciphertext(client)
        return await _post(
            client,
            "/developer/walletSets",
            {
                "idempotencyKey": str(uuid.uuid4()),
                "entitySecretCiphertext": ciphertext,
                "name": name,
            },
        )


async def create_wallet(wallet_set_id: str, ref_id: str = "") -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        ciphertext = await get_entity_secret_ciphertext(client)
        return await _post(
            client,
            "/developer/wallets",
            {
                "idempotencyKey": str(uuid.uuid4()),
                "entitySecretCiphertext": ciphertext,
                "walletSetId": wallet_set_id,
                "blockchains": [config.CIRCLE_BLOCKCHAIN],
                "accountType": "EOA",
                "count": 1,
                "metadata": [{"refId": ref_id}] if ref_id else None,
            },
        )


async def list_wallets(wallet_set_id: str | None = None) -> dict:
    params = {"walletSetId": wallet_set_id} if wallet_set_id else None
    async with httpx.AsyncClient(timeout=30) as client:
        return await _get(client, "/wallets", params)


async def get_wallet_balance(wallet_id: str) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        return await _get(client, f"/wallets/{wallet_id}/balances")


async def contract_execution(wallet_id: str, contract_address: str, abi_signature: str, params: list) -> dict:
    """Execute a contract call from a Circle developer-controlled wallet."""
    async with httpx.AsyncClient(timeout=60) as client:
        ciphertext = await get_entity_secret_ciphertext(client)
        return await _post(
            client,
            "/developer/transactions/contractExecution",
            {
                "idempotencyKey": str(uuid.uuid4()),
                "entitySecretCiphertext": ciphertext,
                "walletId": wallet_id,
                "contractAddress": contract_address,
                "abiFunctionSignature": abi_signature,
                "abiParameters": params,
                "feeLevel": "MEDIUM",
            },
        )


async def get_transaction(tx_id: str) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        return await _get(client, f"/transactions/{tx_id}")
