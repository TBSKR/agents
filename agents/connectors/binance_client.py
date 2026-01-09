"""
Binance Public API Client

Fetch real-time cryptocurrency prices from Binance public API.
No authentication required for ticker prices.

Used by Oracle Timing strategy to detect price threshold crossings
before Polymarket oracles update.
"""

import time
from typing import Optional, Dict, List
from dataclasses import dataclass
import httpx


@dataclass
class PriceFeed:
    """Current price data for a symbol."""
    symbol: str           # e.g., "BTCUSDT"
    price: float          # Current price
    timestamp: float      # Unix timestamp

    def to_dict(self) -> dict:
        return {
            'symbol': self.symbol,
            'price': self.price,
            'timestamp': self.timestamp
        }


@dataclass
class PriceAlert:
    """Alert when price crosses a threshold."""
    symbol: str
    threshold: float
    direction: str        # "above" or "below"
    current_price: float
    crossed: bool
    timestamp: float

    def to_dict(self) -> dict:
        return {
            'symbol': self.symbol,
            'threshold': self.threshold,
            'direction': self.direction,
            'current_price': self.current_price,
            'crossed': self.crossed,
            'timestamp': self.timestamp
        }


class BinanceClient:
    """
    Fetch real-time prices from Binance public API.
    No authentication required for ticker prices.
    """

    BASE_URL = "https://api.binance.com/api/v3"

    # Common symbols mapping (asset -> Binance symbol)
    SYMBOL_MAP = {
        'BTC': 'BTCUSDT',
        'BITCOIN': 'BTCUSDT',
        'ETH': 'ETHUSDT',
        'ETHEREUM': 'ETHUSDT',
        'SOL': 'SOLUSDT',
        'SOLANA': 'SOLUSDT',
        'DOGE': 'DOGEUSDT',
        'DOGECOIN': 'DOGEUSDT',
        'XRP': 'XRPUSDT',
        'ADA': 'ADAUSDT',
        'DOT': 'DOTUSDT',
        'MATIC': 'MATICUSDT',
        'POLYGON': 'MATICUSDT',
        'LINK': 'LINKUSDT',
        'AVAX': 'AVAXUSDT',
        'AVALANCHE': 'AVAXUSDT',
    }

    def __init__(self, timeout: float = 5.0):
        self.timeout = timeout
        self._price_cache: Dict[str, PriceFeed] = {}
        self._cache_ttl = 2.0  # Cache prices for 2 seconds

    def _get_symbol(self, asset: str) -> str:
        """Convert asset name to Binance symbol."""
        asset_upper = asset.upper()
        if asset_upper in self.SYMBOL_MAP:
            return self.SYMBOL_MAP[asset_upper]
        # If already a valid symbol format
        if asset_upper.endswith('USDT'):
            return asset_upper
        # Default to adding USDT
        return f"{asset_upper}USDT"

    def get_price(self, symbol: str = "BTCUSDT") -> Optional[PriceFeed]:
        """
        Get current price for a symbol.

        Args:
            symbol: Binance trading pair (e.g., "BTCUSDT")

        Returns:
            PriceFeed or None if request fails
        """
        # Check cache
        if symbol in self._price_cache:
            cached = self._price_cache[symbol]
            if time.time() - cached.timestamp < self._cache_ttl:
                return cached

        try:
            response = httpx.get(
                f"{self.BASE_URL}/ticker/price",
                params={"symbol": symbol},
                timeout=self.timeout
            )
            if response.status_code == 200:
                data = response.json()
                feed = PriceFeed(
                    symbol=data['symbol'],
                    price=float(data['price']),
                    timestamp=time.time()
                )
                self._price_cache[symbol] = feed
                return feed
        except Exception as e:
            print(f"Binance API error: {e}")
        return None

    def get_price_by_asset(self, asset: str) -> Optional[float]:
        """
        Get current price by asset name (BTC, ETH, etc.).

        Args:
            asset: Asset name (e.g., "BTC", "Bitcoin", "ETH")

        Returns:
            Current price in USD or None
        """
        symbol = self._get_symbol(asset)
        feed = self.get_price(symbol)
        return feed.price if feed else None

    def get_btc_price(self) -> Optional[float]:
        """Get current BTC price."""
        return self.get_price_by_asset("BTC")

    def get_eth_price(self) -> Optional[float]:
        """Get current ETH price."""
        return self.get_price_by_asset("ETH")

    def get_sol_price(self) -> Optional[float]:
        """Get current SOL price."""
        return self.get_price_by_asset("SOL")

    def get_multiple_prices(self, symbols: List[str]) -> Dict[str, Optional[float]]:
        """
        Get prices for multiple symbols.

        Args:
            symbols: List of symbols (e.g., ["BTCUSDT", "ETHUSDT"])

        Returns:
            Dict mapping symbol to price (or None if failed)
        """
        results = {}
        for symbol in symbols:
            binance_symbol = self._get_symbol(symbol)
            feed = self.get_price(binance_symbol)
            results[symbol] = feed.price if feed else None
        return results

    def check_threshold(
        self,
        asset: str,
        threshold: float,
        direction: str
    ) -> PriceAlert:
        """
        Check if asset price has crossed a threshold.

        Args:
            asset: Asset name (e.g., "BTC")
            threshold: Price threshold to check
            direction: "above" or "below"

        Returns:
            PriceAlert with crossed status
        """
        current_price = self.get_price_by_asset(asset)

        if current_price is None:
            return PriceAlert(
                symbol=self._get_symbol(asset),
                threshold=threshold,
                direction=direction,
                current_price=0.0,
                crossed=False,
                timestamp=time.time()
            )

        if direction.lower() == "above":
            crossed = current_price > threshold
        else:
            crossed = current_price < threshold

        return PriceAlert(
            symbol=self._get_symbol(asset),
            threshold=threshold,
            direction=direction,
            current_price=current_price,
            crossed=crossed,
            timestamp=time.time()
        )

    def get_24h_ticker(self, symbol: str = "BTCUSDT") -> Optional[Dict]:
        """
        Get 24-hour ticker statistics.

        Returns dict with: priceChange, priceChangePercent, highPrice, lowPrice, volume
        """
        try:
            response = httpx.get(
                f"{self.BASE_URL}/ticker/24hr",
                params={"symbol": symbol},
                timeout=self.timeout
            )
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            print(f"Binance API error: {e}")
        return None


def test_binance_client():
    """Test the Binance client."""
    client = BinanceClient()

    print("\n" + "="*50)
    print("  BINANCE CLIENT TEST")
    print("="*50)

    # Test BTC price
    btc_price = client.get_btc_price()
    print(f"\n  BTC Price: ${btc_price:,.2f}" if btc_price else "\n  BTC Price: Failed")

    # Test ETH price
    eth_price = client.get_eth_price()
    print(f"  ETH Price: ${eth_price:,.2f}" if eth_price else "  ETH Price: Failed")

    # Test threshold check
    if btc_price:
        alert = client.check_threshold("BTC", 100000, "above")
        print(f"\n  BTC > $100,000: {alert.crossed}")
        print(f"  Current: ${alert.current_price:,.2f}")

    print("\n" + "="*50)


if __name__ == "__main__":
    test_binance_client()
