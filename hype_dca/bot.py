"""Core DCA logic executed on each hourly run.

Flow:
  1. If a bridge is in flight, check for attestation completion.
  2. Check the 2h MA against the price threshold.
  3. If HyperCore USDC balance is low, initiate a CCTP bridge batch.
  4. Otherwise, execute the spot buy.
"""

import logging

from hyperliquid.info import Info

import config
from bridge import get_arbitrum_usdc_balance, initiate_bridge, try_complete_bridge
from bridge_state import clear_state, load_state
from price import fetch_2h_ma
from trader import (
    build_exchange,
    buy_hype_spot,
    get_hypercore_usdc_balance,
    resolve_hype_spot_market,
)

log = logging.getLogger(__name__)


def run_dca() -> None:
    log.info("=== DCA run starting ===")

    # ── Step 1: Resume any in-flight CCTP bridge ──────────────────────────────
    state = load_state()
    if state:
        log.info(
            f"In-flight bridge detected: {state['amount_usdc']} USDC initiated at {state['initiated_at']}"
        )
        completed = try_complete_bridge(state)
        if completed:
            clear_state()
            log.info("Bridge complete — USDC credited to HyperCore. Will trade next cycle.")
            return
        else:
            log.info("Bridge attestation still pending — skipping trade this cycle")
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
        initiate_bridge(config.BRIDGE_BATCH_USDC)
        log.info(
            f"Bridge initiated for {config.BRIDGE_BATCH_USDC:.2f} USDC — "
            "skipping trade this cycle"
        )
        return

    # ── Step 4: Execute spot buy ──────────────────────────────────────────────
    exchange = build_exchange()
    market, sz_dec = resolve_hype_spot_market(info)
    result = buy_hype_spot(exchange, market, sz_dec, current_price)
    log.info(f"Spot buy result: {result}")
    log.info("=== DCA run complete ===")
