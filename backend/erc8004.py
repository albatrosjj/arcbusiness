"""ERC-8004 (Trustless Agents) identity for agreement parties.

ERC-8004 gives each agent an on-chain identity in an Identity Registry
(agentId -> agentDomain + agentAddress). Parties to an ArcBusiness agreement
can register/resolve their agent identity here so agreements are attributable
to verifiable agent identities rather than bare addresses.

If ERC8004_IDENTITY_REGISTRY is not configured, a local in-memory registry is
used as a fallback so the rest of the platform still works on testnet.
"""

from web3 import Web3

from . import chain, config

IDENTITY_REGISTRY_ABI = [
    {
        "type": "function",
        "name": "newAgent",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "agentDomain", "type": "string"},
            {"name": "agentAddress", "type": "address"},
        ],
        "outputs": [{"name": "agentId", "type": "uint256"}],
    },
    {
        "type": "function",
        "name": "resolveByAddress",
        "stateMutability": "view",
        "inputs": [{"name": "agentAddress", "type": "address"}],
        "outputs": [
            {
                "name": "agentInfo",
                "type": "tuple",
                "components": [
                    {"name": "agentId", "type": "uint256"},
                    {"name": "agentDomain", "type": "string"},
                    {"name": "agentAddress", "type": "address"},
                ],
            }
        ],
    },
]

# In-memory fallback registry: address -> {agentId, agentDomain}
_local_registry: dict[str, dict] = {}
_local_next_id = 1


def _registry_contract():
    if not config.ERC8004_IDENTITY_REGISTRY:
        return None
    return chain.w3.eth.contract(
        address=Web3.to_checksum_address(config.ERC8004_IDENTITY_REGISTRY),
        abi=IDENTITY_REGISTRY_ABI,
    )


def register_agent(agent_domain: str, agent_address: str) -> dict:
    global _local_next_id
    agent_address = Web3.to_checksum_address(agent_address)
    registry = _registry_contract()

    if registry is None:
        entry = _local_registry.get(agent_address)
        if entry is None:
            entry = {"agentId": _local_next_id, "agentDomain": agent_domain, "agentAddress": agent_address, "onChain": False}
            _local_registry[agent_address] = entry
            _local_next_id += 1
        return entry

    account = chain.get_account()
    tx_hash = chain.send_tx(registry.functions.newAgent(agent_domain, agent_address), account)
    receipt = chain.wait_receipt(tx_hash)
    return {
        "agentDomain": agent_domain,
        "agentAddress": agent_address,
        "txHash": tx_hash,
        "txLink": chain.tx_link(tx_hash),
        "status": "confirmed" if receipt.status == 1 else "failed",
        "onChain": True,
    }


def resolve_agent(agent_address: str) -> dict | None:
    agent_address = Web3.to_checksum_address(agent_address)
    registry = _registry_contract()

    if registry is None:
        return _local_registry.get(agent_address)

    info = registry.functions.resolveByAddress(agent_address).call()
    if info[0] == 0:
        return None
    return {"agentId": info[0], "agentDomain": info[1], "agentAddress": info[2], "onChain": True}
