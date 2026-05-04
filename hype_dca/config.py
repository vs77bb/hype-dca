import os
from dotenv import load_dotenv

load_dotenv()


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Required env var {name!r} is not set")
    return value


# Wallet
PRIVATE_KEY: str = _require("PRIVATE_KEY")
WALLET_ADDRESS: str = _require("WALLET_ADDRESS")

# RPC endpoints
ALCHEMY_ARBITRUM_RPC: str = _require("ALCHEMY_ARBITRUM_RPC")
HYPER_EVM_RPC: str = os.getenv("HYPER_EVM_RPC", "https://rpc.hyperliquid.xyz/evm")

# DCA parameters
MA_THRESHOLD_USD: float = float(_require("MA_THRESHOLD_USD"))
MA_PERIODS: int = int(os.getenv("MA_PERIODS", "20"))
DAILY_BUY_USDC: float = float(os.getenv("DAILY_BUY_USDC", "10.0"))
MIN_SPOT_ORDER_USDC: float = float(os.getenv("MIN_SPOT_ORDER_USDC", "10.0"))
BUY_COOLDOWN_HOURS: float = float(os.getenv("BUY_COOLDOWN_HOURS", "24.0"))

# Bridge parameters
BRIDGE_BUFFER_DAYS: int = int(os.getenv("BRIDGE_BUFFER_DAYS", "7"))
BRIDGE_BATCH_DAYS: int = int(os.getenv("BRIDGE_BATCH_DAYS", "14"))
BRIDGE_BUFFER_USDC: float = DAILY_BUY_USDC * BRIDGE_BUFFER_DAYS
BRIDGE_BATCH_USDC: float = DAILY_BUY_USDC * BRIDGE_BATCH_DAYS
BRIDGE_ATTESTATION_WAIT_SECONDS: int = int(os.getenv("BRIDGE_ATTESTATION_WAIT_SECONDS", "0"))
BRIDGE_ATTESTATION_POLL_SECONDS: int = int(os.getenv("BRIDGE_ATTESTATION_POLL_SECONDS", "30"))

# Arbitrum contract addresses
ARBITRUM_USDC = "0xaf88d065e77c8cC2239327C5EDb3A432268e5831"
HYPER_EVM_NATIVE_USDC = os.getenv(
    "HYPER_EVM_NATIVE_USDC",
    "0xb88339CB7199b77E23DB6E890353E22632Ba630f",
)
# CCTP V2 contracts — Hyperliquid integrated CCTP V2 (not V1)
# Source: https://developers.circle.com/cctp/evm-smart-contracts
CCTP_TOKEN_MESSENGER = "0x28b5a0e9C621a5BadaA536219b3a228C8168cf5d"
CCTP_MSG_TRANSMITTER = "0x81D40F21F12A8F0E3252Bccb954D722d4c464B64"

# Circle CCTP domain IDs
ARBITRUM_CCTP_DOMAIN = 3
HYPER_EVM_CCTP_DOMAIN = 19  # HyperEVM domain; verify at https://developers.circle.com/cctp/cctp-supported-blockchains

# Circle attestation API
CIRCLE_ATTESTATION_URL = "https://iris-api.circle.com/v2/messages"

# Hyperliquid API
HL_API_URL = "https://api.hyperliquid.xyz"
