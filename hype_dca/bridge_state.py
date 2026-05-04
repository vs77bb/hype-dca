"""Persist CCTP bridge state across hourly scheduler runs.

The bridge is a 2-phase async operation (~15-19 min). State is written to
bridge_state.json so the process can be restarted without losing track of an
in-flight bridge.
"""

import json
import os
from datetime import datetime, timezone
from typing import TypedDict

STATE_FILE = os.path.join(os.path.dirname(__file__), "bridge_state.json")


class BridgeState(TypedDict):
    phase: str          # "awaiting_attestation"
    message_hash: str   # 0x-prefixed hex keccak256 of the raw CCTP message
    message_hex: str    # 0x-prefixed hex of the raw CCTP message bytes
    tx_hash: str        # 0x-prefixed Arbitrum depositForBurn transaction hash
    amount_usdc: float
    initiated_at: str   # ISO-8601 UTC


def load_state() -> BridgeState | None:
    if not os.path.exists(STATE_FILE):
        return None
    with open(STATE_FILE) as f:
        return json.load(f)


def save_state(state: BridgeState) -> None:
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def clear_state() -> None:
    if os.path.exists(STATE_FILE):
        os.remove(STATE_FILE)


def new_state(
    message_hash: str,
    message_hex: str,
    tx_hash: str,
    amount_usdc: float,
) -> BridgeState:
    return BridgeState(
        phase="awaiting_attestation",
        message_hash=message_hash,
        message_hex=message_hex,
        tx_hash=tx_hash,
        amount_usdc=amount_usdc,
        initiated_at=datetime.now(timezone.utc).isoformat(),
    )
