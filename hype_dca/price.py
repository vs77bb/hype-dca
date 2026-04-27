import time
import statistics

from hyperliquid.info import Info

from config import HL_API_URL, MA_PERIODS


def fetch_2h_ma() -> tuple[float, float]:
    """Fetch HYPE candles and return (current_price, moving_average).

    The MA is the simple mean of the last MA_PERIODS 2h close prices.
    Raises ValueError if the API returns insufficient candle data.
    """
    info = Info(HL_API_URL, skip_ws=True)
    now_ms = int(time.time() * 1000)
    # Request extra candles as a buffer in case the latest candle is still open
    start_ms = now_ms - (MA_PERIODS + 3) * 2 * 3600 * 1000

    candles = info.candles_snapshot("HYPE", "2h", start_ms, now_ms)

    if len(candles) < MA_PERIODS:
        raise ValueError(
            f"Insufficient candle data: received {len(candles)}, need {MA_PERIODS}"
        )

    closes = [float(c["c"]) for c in candles[-MA_PERIODS:]]
    ma = statistics.mean(closes)
    current_price = float(candles[-1]["c"])
    return current_price, ma
