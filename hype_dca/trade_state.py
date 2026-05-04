"""Persist trading state across scheduled one-shot runs."""

import json
import os
from datetime import datetime, timezone
from typing import TypedDict

STATE_FILE = os.path.join(os.path.dirname(__file__), "trade_state.json")


class TradeState(TypedDict, total=False):
    last_buy_at: str


def load_trade_state() -> TradeState:
    if not os.path.exists(STATE_FILE):
        return {}
    with open(STATE_FILE) as f:
        return json.load(f)


def record_buy() -> None:
    state = load_trade_state()
    state["last_buy_at"] = datetime.now(timezone.utc).isoformat()
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def last_buy_at() -> datetime | None:
    value = load_trade_state().get("last_buy_at")
    if not value:
        return None
    return datetime.fromisoformat(value)
