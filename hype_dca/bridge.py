"""CCTP V2 bridge: Arbitrum USDC → HyperEVM → HyperCore.

Phase 1 (initiate_bridge):
  - Approve USDC to CCTP TokenMessenger on Arbitrum
  - Call depositForBurn → persists bridge state to bridge_state.json

Phase 2 (try_complete_bridge):
  - Poll Circle attestation API until signed attestation is ready
  - Submit attestation to MessageTransmitter on HyperEVM → native USDC minted to our wallet
  - Approve native USDC to CoreDepositWallet + call deposit() → USDC credited to HyperCore
  - Returns True when complete, False if attestation not yet available

Two distinct contracts on HyperEVM:
  - Native USDC ERC20: what CCTP mints to our wallet (address extracted from mint receipt)
  - CoreDepositWallet: bridge contract that moves ERC20 USDC into HyperCore
    (address fetched from spotMeta API at runtime — do not hardcode)
"""

import logging

import requests
from web3 import Web3

import config
from bridge_state import BridgeState, new_state, save_state

log = logging.getLogger(__name__)

# ── Minimal ABIs ─────────────────────────────────────────────────────────────

ERC20_ABI = [
    {"name": "approve", "type": "function", "stateMutability": "nonpayable",
     "inputs": [{"name": "spender", "type": "address"}, {"name": "amount", "type": "uint256"}],
     "outputs": [{"name": "", "type": "bool"}]},
    {"name": "balanceOf", "type": "function", "stateMutability": "view",
     "inputs": [{"name": "account", "type": "address"}],
     "outputs": [{"name": "", "type": "uint256"}]},
    # ERC20 Transfer event — used to identify minted USDC address from CCTP receipt
    {"name": "Transfer", "type": "event",
     "inputs": [
         {"name": "from", "type": "address", "indexed": True},
         {"name": "to", "type": "address", "indexed": True},
         {"name": "value", "type": "uint256", "indexed": False},
     ]},
]

# CCTP V2 TokenMessenger
# depositForBurn(uint256,uint32,bytes32,address,bytes32,uint256,uint32)
TOKEN_MESSENGER_ABI = [
    {"name": "depositForBurn", "type": "function", "stateMutability": "nonpayable",
     "inputs": [
         {"name": "amount", "type": "uint256"},
         {"name": "destinationDomain", "type": "uint32"},
         {"name": "mintRecipient", "type": "bytes32"},
         {"name": "burnToken", "type": "address"},
         {"name": "destinationCaller", "type": "bytes32"},
         {"name": "maxFee", "type": "uint256"},
         {"name": "minFinalityThreshold", "type": "uint32"},
     ],
     "outputs": []},
]

# MessageTransmitter emits MessageSent(bytes) — same event in V1 and V2
MESSAGE_SENT_TOPIC = Web3.keccak(text="MessageSent(bytes)").hex()

MSG_TRANSMITTER_ABI = [
    {"name": "receiveMessage", "type": "function", "stateMutability": "nonpayable",
     "inputs": [
         {"name": "message", "type": "bytes"},
         {"name": "attestation", "type": "bytes"},
     ],
     "outputs": [{"name": "success", "type": "bool"}]},
]

DEPOSIT_WALLET_ABI = [
    {"name": "deposit", "type": "function", "stateMutability": "nonpayable",
     "inputs": [
         {"name": "amount", "type": "uint256"},
         {"name": "destinationDex", "type": "uint32"},
     ],
     "outputs": []},
]

# ERC20 Transfer topic: keccak256("Transfer(address,address,uint256)")
ERC20_TRANSFER_TOPIC = Web3.keccak(text="Transfer(address,address,uint256)").hex()
HYPERCORE_SPOT_DEX = 2**32 - 1


# ── Helpers ───────────────────────────────────────────────────────────────────

def _to_bytes32(address: str) -> bytes:
    """Left-pad an EVM address to 32 bytes (CCTP mintRecipient format)."""
    return b"\x00" * 12 + bytes.fromhex(address.removeprefix("0x"))


def _build_and_send(w3: Web3, fn, from_address: str, private_key: str) -> object:
    """Build, sign, send a contract call and wait for receipt. Returns receipt."""
    gas_limit = fn.estimate_gas({"from": from_address})
    max_priority = w3.eth.max_priority_fee
    base_fee = w3.eth.get_block("latest")["baseFeePerGas"]
    max_fee = max_priority + (2 * base_fee)
    min_required_balance = gas_limit * max_fee
    native_balance = w3.eth.get_balance(from_address)
    if native_balance < min_required_balance:
        have = float(w3.from_wei(native_balance, "ether"))
        need = float(w3.from_wei(min_required_balance, "ether"))
        raise RuntimeError(
            f"Insufficient native gas balance for transaction. "
            f"Have {have:.8f}, need at least {need:.8f}."
        )
    tx = fn.build_transaction({
        "from": from_address,
        "nonce": w3.eth.get_transaction_count(from_address),
        "gas": gas_limit,
        "maxFeePerGas": max_fee,
        "maxPriorityFeePerGas": max_priority,
    })
    signed = w3.eth.account.sign_transaction(tx, private_key)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    if receipt["status"] != 1:
        raise RuntimeError(f"Transaction reverted: {tx_hash.hex()}")
    return receipt


def _fetch_core_deposit_wallet() -> str:
    """Return the CoreDepositWallet address from Hyperliquid's spotMeta API.

    This is the bridge contract on HyperEVM that accepts ERC20 USDC and credits
    the equivalent amount to HyperCore. Call deposit(amount) after approving USDC.
    """
    resp = requests.post(
        f"{config.HL_API_URL}/info",
        json={"type": "spotMeta"},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    for token in data.get("tokens", []):
        evm_contract = token.get("evmContract")
        if evm_contract and token.get("name") == "USDC":
            return Web3.to_checksum_address(evm_contract["address"])
    raise RuntimeError("CoreDepositWallet not found in spotMeta response")


def get_arbitrum_usdc_balance() -> float:
    w3 = Web3(Web3.HTTPProvider(config.ALCHEMY_ARBITRUM_RPC))
    usdc = w3.eth.contract(
        address=Web3.to_checksum_address(config.ARBITRUM_USDC), abi=ERC20_ABI
    )
    raw = usdc.functions.balanceOf(
        Web3.to_checksum_address(config.WALLET_ADDRESS)
    ).call()
    return raw / 1e6


# ── Phase 1: Burn on Arbitrum ─────────────────────────────────────────────────

def initiate_bridge(amount_usdc: float) -> None:
    """Approve + depositForBurn on Arbitrum. Persists state to bridge_state.json."""
    amount_raw = int(amount_usdc * 1e6)
    w3 = Web3(Web3.HTTPProvider(config.ALCHEMY_ARBITRUM_RPC))
    wallet = Web3.to_checksum_address(config.WALLET_ADDRESS)
    messenger_addr = Web3.to_checksum_address(config.CCTP_TOKEN_MESSENGER)
    usdc_addr = Web3.to_checksum_address(config.ARBITRUM_USDC)

    usdc = w3.eth.contract(address=usdc_addr, abi=ERC20_ABI)
    messenger = w3.eth.contract(address=messenger_addr, abi=TOKEN_MESSENGER_ABI)

    log.info(f"Approving {amount_usdc} USDC to CCTP TokenMessenger on Arbitrum")
    _build_and_send(w3, usdc.functions.approve(messenger_addr, amount_raw), wallet, config.PRIVATE_KEY)

    log.info(f"Calling depositForBurn → HyperEVM domain {config.HYPER_EVM_CCTP_DOMAIN}")
    # depositForBurn uses a fixed gas limit because estimate_gas can be unreliable for cross-chain calls
    tx = messenger.functions.depositForBurn(
        amount_raw,
        config.HYPER_EVM_CCTP_DOMAIN,
        _to_bytes32(config.WALLET_ADDRESS),
        usdc_addr,
        b"\x00" * 32,  # destinationCaller = anyone can call receiveMessage on destination
        0,             # maxFee = 0 for standard transfer
        2000,          # minFinalityThreshold = finalized transfer
    ).build_transaction({
        "from": wallet,
        "nonce": w3.eth.get_transaction_count(wallet),
        "gas": 250_000,
        "maxFeePerGas": w3.eth.max_priority_fee + (2 * w3.eth.get_block("latest")["baseFeePerGas"]),
        "maxPriorityFeePerGas": w3.eth.max_priority_fee,
    })
    signed = w3.eth.account.sign_transaction(tx, config.PRIVATE_KEY)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    if receipt["status"] != 1:
        raise RuntimeError(f"depositForBurn reverted: {tx_hash.hex()}")

    # Extract raw message bytes from MessageSent event emitted by MessageTransmitter
    # Log data layout: 32-byte ABI offset + 32-byte length + message bytes
    message_bytes: bytes | None = None
    for log_entry in receipt["logs"]:
        if log_entry["topics"][0].hex() == MESSAGE_SENT_TOPIC:
            raw_data = bytes(log_entry["data"])
            msg_len = int.from_bytes(raw_data[32:64], "big")
            message_bytes = raw_data[64: 64 + msg_len]
            break

    if message_bytes is None:
        raise RuntimeError("MessageSent event not found in depositForBurn receipt")

    message_hash = "0x" + Web3.keccak(message_bytes).hex()
    message_hex = "0x" + message_bytes.hex()
    tx_hash_hex = "0x" + tx_hash.hex()
    state = new_state(message_hash, message_hex, tx_hash_hex, amount_usdc)
    save_state(state)
    log.info(f"Bridge initiated. tx={tx_hash_hex} message_hash={message_hash}")


# ── Phase 2: Receive attestation on HyperEVM + deposit to HyperCore ──────────

def try_complete_bridge(state: BridgeState) -> bool:
    """Check attestation and complete the bridge if ready.

    Returns True when USDC is fully deposited to HyperCore, False if still pending.
    """
    tx_hash = state.get("tx_hash")
    if not tx_hash:
        raise RuntimeError(
            "Bridge state is missing tx_hash. Add the Arbitrum depositForBurn "
            "transaction hash to bridge_state.json, then rerun."
        )

    resp = requests.get(
        f"{config.CIRCLE_ATTESTATION_URL}/{config.ARBITRUM_CCTP_DOMAIN}",
        params={"transactionHash": tx_hash},
        timeout=15,
    )
    if resp.status_code == 404:
        log.info("Attestation not yet indexed by Circle — will retry next cycle")
        return False

    resp.raise_for_status()
    data = resp.json()
    messages = data.get("messages", [])
    if not messages or messages[0].get("status") != "complete":
        log.info("Attestation status=pending — will retry next cycle")
        return False

    attestation_hex: str = messages[0]["attestation"]
    attestation_bytes = bytes.fromhex(attestation_hex.removeprefix("0x"))
    message_hex = messages[0].get("message") or state["message_hex"]
    message_bytes = bytes.fromhex(message_hex.removeprefix("0x"))
    amount_raw = int(state["amount_usdc"] * 1e6)

    w3 = Web3(Web3.HTTPProvider(config.HYPER_EVM_RPC))
    wallet = Web3.to_checksum_address(config.WALLET_ADDRESS)
    native_usdc_addr = Web3.to_checksum_address(config.HYPER_EVM_NATIVE_USDC)
    native_usdc = w3.eth.contract(address=native_usdc_addr, abi=ERC20_ABI)
    native_usdc_balance = native_usdc.functions.balanceOf(wallet).call()

    if native_usdc_balance >= amount_raw:
        usdc_erc20_addr = native_usdc_addr
        log.info(
            f"Native USDC already present on HyperEVM: {native_usdc_balance / 1e6:.2f}"
        )
    else:
        # Submit attestation → mints native USDC to our wallet on HyperEVM
        log.info("Submitting CCTP attestation to HyperEVM MessageTransmitter")
        transmitter = w3.eth.contract(
            address=Web3.to_checksum_address(config.CCTP_MSG_TRANSMITTER),
            abi=MSG_TRANSMITTER_ABI,
        )
        mint_receipt = _build_and_send(
            w3,
            transmitter.functions.receiveMessage(message_bytes, attestation_bytes),
            wallet,
            config.PRIVATE_KEY,
        )

        # Identify the native USDC ERC20 address from the mint receipt:
        # CCTP mints by emitting Transfer(from=address(0), to=wallet, value=amount).
        # The log's address field is the USDC ERC20 contract on HyperEVM.
        usdc_erc20_addr = None
        wallet_lower = wallet.lower()
        for log_entry in mint_receipt["logs"]:
            topics = log_entry["topics"]
            if (
                len(topics) >= 3
                and topics[0].hex() == ERC20_TRANSFER_TOPIC
                and topics[1].hex()[-40:] == "00" * 20  # from = address(0)
                and topics[2].hex()[-40:].lower() == wallet_lower.removeprefix("0x")
            ):
                usdc_erc20_addr = Web3.to_checksum_address(log_entry["address"])
                break

        if usdc_erc20_addr is None:
            raise RuntimeError(
                "Could not identify minted USDC ERC20 address from receiveMessage receipt"
            )
        log.info(f"Native USDC on HyperEVM: {usdc_erc20_addr}")

    # Fetch CoreDepositWallet (bridge contract: moves ERC20 USDC → HyperCore)
    core_deposit_wallet = _fetch_core_deposit_wallet()
    log.info(f"CoreDepositWallet: {core_deposit_wallet}")

    # Approve native USDC to CoreDepositWallet
    hyper_usdc = w3.eth.contract(address=usdc_erc20_addr, abi=ERC20_ABI)
    log.info(f"Approving {state['amount_usdc']} USDC to CoreDepositWallet on HyperEVM")
    _build_and_send(
        w3,
        hyper_usdc.functions.approve(core_deposit_wallet, amount_raw),
        wallet,
        config.PRIVATE_KEY,
    )

    # Deposit to HyperCore
    deposit_wallet = w3.eth.contract(address=core_deposit_wallet, abi=DEPOSIT_WALLET_ABI)
    log.info(f"Depositing {state['amount_usdc']} USDC to HyperCore spot")
    _build_and_send(
        w3,
        deposit_wallet.functions.deposit(amount_raw, HYPERCORE_SPOT_DEX),
        wallet,
        config.PRIVATE_KEY,
    )
    log.info("USDC successfully deposited to HyperCore")
    return True
