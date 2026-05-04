from web3 import Web3
from bridge import get_arbitrum_usdc_balance
from trader import get_hypercore_usdc_balance
from hyperliquid.info import Info
import config

arb_w3 = Web3(Web3.HTTPProvider(config.ALCHEMY_ARBITRUM_RPC))
hyper_w3 = Web3(Web3.HTTPProvider(config.HYPER_EVM_RPC))
wallet = Web3.to_checksum_address(config.WALLET_ADDRESS)

arb_eth = arb_w3.eth.get_balance(wallet) / 1e18
hyper_hype = hyper_w3.eth.get_balance(wallet) / 1e18

print(f"Arbitrum  USDC: ${get_arbitrum_usdc_balance():.2f}")
print(f"Arbitrum  ETH (gas):   {arb_eth:.6f}")
print()
info = Info(config.HL_API_URL, skip_ws=True)
print(f"HyperCore USDC: ${get_hypercore_usdc_balance(info):.2f}")
print(f"HyperEVM  HYPE (gas): {hyper_hype:.6f}")
