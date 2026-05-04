"""Core DCA logic executed on each hourly run.

Flow:
  1. If a bridge is in flight, check for attestation completion.
  2. If the bridge completes, continue into the normal buy flow.
  3. Check the 2h MA against the price threshold.
  4. If HyperCore USDC balance is low, initiate a CCTP bridge batch.
  5. Otherwise, execute the spot buy.
"""

import logging
import time
from datetime import datetime, timedelta, timezone

from hyperliquid.info import Info

import config
from bridge import get_arbitrum_usdc_balance, initiate_bridge, try_complete_bridge
from bridge_state import clear_state, load_state
from price import fetch_2h_ma
from trade_state import last_buy_at, record_buy
from trader import (
    build_exchange,
    buy_hype_spot,
    get_hypercore_usdc_balance,
    resolve_hype_spot_market,
)

log = logging.getLogger(__name__)


def _complete_bridge_when_ready(state) -> bool:
    """Poll Circle until an in-flight bridge completes or the wait budget expires."""
    deadline = time.monotonic() + config.BRIDGE_ATTESTATION_WAIT_SECONDS
    attempt = 0

    while True:
        attempt += 1
        try:
            completed = try_complete_bridge(state)
        except Exception as exc:
            log.error(f"Bridge completion failed: {exc}")
            return False

        if completed:
            clear_state()
            log.info("Bridge complete — USDC credited to HyperCore. Continuing to buy flow.")
            return True

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            log.info("Bridge attestation still pending — skipping trade this cycle")
            return False

        sleep_seconds = min(config.BRIDGE_ATTESTATION_POLL_SECONDS, remaining)
        log.info(
            f"Bridge attestation pending; retrying in {sleep_seconds:.0f}s "
            f"(attempt {attempt})"
        )
        time.sleep(sleep_seconds)


def run_dca() -> None:
    log.info("=== DCA run starting ===")

    # ── Step 1: Resume any in-flight CCTP bridge ──────────────────────────────
    state = load_state()
    if state:
        log.info(
            f"In-flight bridge detected: {state['amount_usdc']} USDC initiated at {state['initiated_at']}"
        )
        if not _complete_bridge_when_ready(state):
            return

    # ── Step 2: Price condition ───────────────────────────────────────────────
    try:
        current_price, ma = fetch_2h_ma()
    except Exception as exc:
        log.error(f"Price fetch failed: {exc}")
        return

    log.info(
        f"HYPE price={current_price:.4f}  2h MA ({config.MA_PERIODS}p)={ma:.4f}  "
        f"threshold={config.MA_THRESHOLD_USD}"
    )

    if ma >= config.MA_THRESHOLD_USD:
        log.info("MA is at or above threshold — no buy this cycle")
        return

    previous_buy_at = last_buy_at()
    if previous_buy_at:
        next_buy_at = previous_buy_at + timedelta(hours=config.BUY_COOLDOWN_HOURS)
        now = datetime.now(timezone.utc)
        if now < next_buy_at:
            log.info(f"Buy cooldown active until {next_buy_at.isoformat()}")
            return

    # ── Step 3: Check HyperCore balance; bridge if low ────────────────────────
    info = Info(config.HL_API_URL, skip_ws=True)
    hypercore_bal = get_hypercore_usdc_balance(info)
    log.info(f"HyperCore USDC balance: {hypercore_bal:.2f}")

    if hypercore_bal < config.BRIDGE_BUFFER_USDC:
        log.info(
            f"Balance {hypercore_bal:.2f} < buffer {config.BRIDGE_BUFFER_USDC:.2f} — "
            "initiating bridge"
        )
        arb_bal = get_arbitrum_usdc_balance()
        if arb_bal < config.BRIDGE_BATCH_USDC:
            log.error(
                f"Arbitrum USDC balance {arb_bal:.2f} is below batch size "
                f"{config.BRIDGE_BATCH_USDC:.2f} — cannot bridge"
            )
            return
        try:
            initiate_bridge(config.BRIDGE_BATCH_USDC)
        except Exception as exc:
            log.error(f"Bridge initiation failed: {exc}")
            return
        log.info(f"Bridge initiated for {config.BRIDGE_BATCH_USDC:.2f} USDC")

        state = load_state()
        if not state or not _complete_bridge_when_ready(state):
            return

        try:
            current_price, ma = fetch_2h_ma()
        except Exception as exc:
            log.error(f"Price refresh after bridge failed: {exc}")
            return

        log.info(
            f"Refreshed HYPE price={current_price:.4f}  2h MA ({config.MA_PERIODS}p)="
            f"{ma:.4f}  threshold={config.MA_THRESHOLD_USD}"
        )
        if ma >= config.MA_THRESHOLD_USD:
            log.info("MA is at or above threshold after bridge — no buy this cycle")
            return

    # ── Step 4: Execute spot buy ──────────────────────────────────────────────
    exchange = build_exchange()
    market, sz_dec = resolve_hype_spot_market(info)
    try:
        result = buy_hype_spot(exchange, market, sz_dec, current_price)
    except Exception as exc:
        log.error(f"Spot buy failed: {exc}")
        return
    record_buy()
    log.info(f"Spot buy result: {result}")
    log.info("=== DCA run complete ===")
