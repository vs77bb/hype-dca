"""Hyperliquid spot trading: resolve the HYPE market, check balance, place buy."""

import logging
from eth_account import Account
from hyperliquid.exchange import Exchange
from hyperliquid.info import Info

import config

log = logging.getLogger(__name__)


def resolve_hype_spot_market(info: Info) -> tuple[str, int]:
    """Return (market_name, sz_decimals) for the HYPE/USDC spot pair.

    Market name is dynamic (e.g. "@107") and must not be hardcoded — token
    indices can shift as new assets are listed.
    """
    meta = info.spot_meta()
    tokens = meta.get("tokens", [])
    universe = meta.get("universe", [])

    # Find the HYPE token index
    hype_index: int | None = None
    for i, token in enumerate(tokens):
        if token.get("name") == "HYPE":
            hype_index = i
            break

    if hype_index is None:
        raise RuntimeError("HYPE token not found in spot metadata")

    # Find the market that contains HYPE as one of its tokens
    # Each universe entry has a "tokens" list [baseIndex, quoteIndex]
    for market in universe:
        market_tokens = market.get("tokens", [])
        if hype_index in market_tokens:
            sz_decimals: int = market.get("szDecimals", 4)
            market_name: str = market.get("name", "")
            log.info(f"Resolved HYPE spot market: {market_name!r} szDecimals={sz_decimals}")
            return market_name, sz_decimals

    raise RuntimeError("HYPE spot market not found in universe metadata")


def get_hypercore_usdc_balance(info: Info) -> float:
    """Return the USDC balance (spot) on HyperCore for the configured wallet."""
    state = info.spot_user_state(config.WALLET_ADDRESS)
    for entry in state.get("balances", []):
        if entry.get("coin") == "USDC":
            return float(entry.get("total", 0))
    return 0.0


def buy_hype_spot(
    exchange: Exchange,
    market: str,
    sz_decimals: int,
    current_price: float,
) -> dict:
    """Place a market buy for DAILY_BUY_USDC worth of HYPE on the spot market.

    Uses IOC market order (market_open internally converts to a limit with slippage).
    """
    size = round(config.DAILY_BUY_USDC / current_price, sz_decimals)
    log.info(
        f"Placing spot buy: {size} HYPE @ ~{current_price:.4f} "
        f"(~${config.DAILY_BUY_USDC:.2f} USDC) on {market}"
    )
    result = exchange.market_open(market, is_buy=True, sz=size, slippage=0.01)
    return result


def build_exchange() -> Exchange:
    account = Account.from_key(config.PRIVATE_KEY)
    return Exchange(account, config.HL_API_URL)
