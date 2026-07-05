"""Email + OTP login backed by Circle User Controlled Wallets.

Flow: email -> OTP (printed to server console; also returned on testnet for
easy demoing) -> Circle user is created and a wallet is provisioned on
ARC-TESTNET on first login.

Wallet provisioning: we register the user with Circle (POST /users), acquire
a user token (POST /users/token) and call POST /user/initialize with
accountType SCA. Completing the PIN challenge requires Circle's client SDK,
so if no user-controlled wallet materializes we provision a
developer-controlled SCA wallet tagged with the user's email (refId) in a
dedicated wallet set — that wallet can sign transactions server-side, which
is what powers the agreement actions.
"""

import asyncio
import uuid

from . import circle_wallets, config, user_store

USER_NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")
WALLET_SET_NAME = "arcbusiness-users"


def circle_user_id(email: str) -> str:
    """Deterministic Circle userId derived from the email."""
    return str(uuid.uuid5(USER_NAMESPACE, f"arcbusiness:{email.lower()}"))


async def _ensure_wallet_set() -> str:
    ws_id = user_store.get_meta("wallet_set_id")
    if ws_id:
        return ws_id
    data = await circle_wallets.create_wallet_set(WALLET_SET_NAME)
    ws_id = data["walletSet"]["id"]
    user_store.set_meta("wallet_set_id", ws_id)
    return ws_id


async def provision_wallet(email: str) -> dict:
    """Create the Circle user and get them an Arc Testnet wallet. Idempotent."""
    existing = user_store.get_user(email)
    if existing and existing.get("wallet_address"):
        return existing

    user_id = circle_user_id(email)
    user = {"email": email, "circle_user_id": user_id}

    # 1. Register the end user with Circle and grab a session token.
    await circle_wallets.create_user(user_id)
    token_data = await circle_wallets.get_user_token(user_id)
    user_token = token_data.get("userToken", "")

    # 2. Ask Circle to initialize the user with an SCA wallet on ARC-TESTNET.
    if user_token:
        try:
            init = await circle_wallets.initialize_user(user_token)
            user["init_challenge_id"] = init.get("challengeId")
        except circle_wallets.CircleError as e:
            user["init_error"] = str(e)[:200]

        # The wallet appears once initialization completes; poll briefly.
        for _ in range(3):
            try:
                wallets = (await circle_wallets.list_user_wallets(user_token)).get("wallets", [])
            except circle_wallets.CircleError:
                wallets = []
            arc = [w for w in wallets if w.get("blockchain") == config.CIRCLE_BLOCKCHAIN]
            if arc:
                user.update(
                    wallet_id=arc[0]["id"],
                    wallet_address=arc[0]["address"],
                    wallet_type="user",
                )
                break
            await asyncio.sleep(2)

    # 3. Fallback: developer-controlled SCA wallet tagged with the email, so
    #    the backend can sign agreement transactions on the user's behalf.
    if not user.get("wallet_address"):
        ws_id = await _ensure_wallet_set()
        data = await circle_wallets.create_wallet(ws_id, ref_id=email, account_type="SCA")
        w = data["wallets"][0]
        user.update(wallet_id=w["id"], wallet_address=w["address"], wallet_type="developer")

    user_store.save_user(email, user)
    return user
