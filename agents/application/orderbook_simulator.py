"""
Order Book Simulator - Generates synthetic order books for realistic paper trading.

This module provides:
- Synthetic order book generation based on market conditions
- Order book walking for accurate fill simulation
- Integration with the Gamma API for real data when available
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Tuple
import math
import random

from agents.application.spread_model import SpreadModel, PolymarketSpreadModel
from agents.application.fill_simulator import Fill, ExecutionResult, OrderSide


@dataclass
class OrderBookLevel:
    """A single price level in the order book."""
    price: float
    size: float  # Quantity available at this price

    @property
    def value(self) -> float:
        """Total dollar value at this level."""
        return self.price * self.size


@dataclass
class SimulatedOrderBook:
    """Complete order book with bids and asks."""
    bids: List[OrderBookLevel]  # Sorted descending by price (best bid first)
    asks: List[OrderBookLevel]  # Sorted ascending by price (best ask first)
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def best_bid(self) -> float:
        """Best (highest) bid price."""
        return self.bids[0].price if self.bids else 0

    @property
    def best_ask(self) -> float:
        """Best (lowest) ask price."""
        return self.asks[0].price if self.asks else 1

    @property
    def mid_price(self) -> float:
        """Mid-market price."""
        if not self.bids or not self.asks:
            return 0.5
        return (self.best_bid + self.best_ask) / 2

    @property
    def spread(self) -> float:
        """Bid-ask spread as decimal."""
        if self.mid_price == 0:
            return 0
        return (self.best_ask - self.best_bid) / self.mid_price

    @property
    def total_bid_liquidity(self) -> float:
        """Total liquidity on the bid side."""
        return sum(level.value for level in self.bids)

    @property
    def total_ask_liquidity(self) -> float:
        """Total liquidity on the ask side."""
        return sum(level.value for level in self.asks)

    def get_bid_depth_at_price(self, price: float) -> float:
        """Get total bid liquidity at or above a given price."""
        return sum(level.value for level in self.bids if level.price >= price)

    def get_ask_depth_at_price(self, price: float) -> float:
        """Get total ask liquidity at or below a given price."""
        return sum(level.value for level in self.asks if level.price <= price)


class OrderBookSimulator:
    """
    Generates realistic synthetic order books for paper trading.

    Uses market conditions to create order books that reflect:
    - Market liquidity distribution
    - Price levels based on spread model
    - Realistic depth decay
    """

    # Configuration
    DEFAULT_LEVELS = 10  # Number of price levels on each side
    DEPTH_DECAY_RATE = 0.7  # How quickly liquidity decays at worse prices

    def __init__(
        self,
        spread_model: SpreadModel = None,
        num_levels: int = None,
        random_seed: int = None
    ):
        """
        Initialize the order book simulator.

        Args:
            spread_model: Model for calculating spreads
            num_levels: Number of price levels on each side
            random_seed: Seed for reproducible randomness
        """
        self.spread_model = spread_model or PolymarketSpreadModel()
        self.num_levels = num_levels or self.DEFAULT_LEVELS

        if random_seed is not None:
            random.seed(random_seed)

    def generate_synthetic_orderbook(
        self,
        mid_price: float,
        total_liquidity: float,
        spread: float = None,
        volatility: float = 0
    ) -> SimulatedOrderBook:
        """
        Generate a synthetic order book based on market parameters.

        Args:
            mid_price: The mid-market price
            total_liquidity: Total dollar liquidity to distribute
            spread: Bid-ask spread (if None, calculated from spread model)
            volatility: Market volatility for spread calculation

        Returns:
            SimulatedOrderBook with synthetic bids and asks
        """
        # Calculate spread if not provided
        if spread is None:
            spread = self.spread_model.calculate_spread(
                liquidity=total_liquidity,
                volatility=volatility
            )

        # Split spread between bid and ask
        half_spread = spread / 2
        best_bid = mid_price * (1 - half_spread)
        best_ask = mid_price * (1 + half_spread)

        # Split liquidity between sides (roughly equal with some variance)
        bid_liquidity = total_liquidity * random.uniform(0.45, 0.55)
        ask_liquidity = total_liquidity - bid_liquidity

        # Generate bid levels (decreasing prices)
        bids = self._generate_levels(
            start_price=best_bid,
            direction=-1,  # Prices decrease
            total_liquidity=bid_liquidity,
            mid_price=mid_price
        )

        # Generate ask levels (increasing prices)
        asks = self._generate_levels(
            start_price=best_ask,
            direction=1,  # Prices increase
            total_liquidity=ask_liquidity,
            mid_price=mid_price
        )

        return SimulatedOrderBook(bids=bids, asks=asks)

    def _generate_levels(
        self,
        start_price: float,
        direction: int,
        total_liquidity: float,
        mid_price: float
    ) -> List[OrderBookLevel]:
        """
        Generate order book levels for one side.

        Args:
            start_price: Best price on this side
            direction: -1 for bids (decreasing), +1 for asks (increasing)
            total_liquidity: Total dollar liquidity to distribute
            mid_price: Mid-market price for reference

        Returns:
            List of OrderBookLevel objects
        """
        levels = []
        remaining_liquidity = total_liquidity

        # Price step between levels (proportional to spread)
        price_step = abs(start_price - mid_price) * 0.3  # 30% of half-spread per level

        for i in range(self.num_levels):
            if remaining_liquidity < 1:  # Less than $1 remaining
                break

            # Calculate price for this level
            price = start_price + (direction * price_step * i)

            # Ensure price stays valid (0-1 for prediction markets)
            if price <= 0 or price >= 1:
                break

            # Calculate liquidity at this level (exponential decay)
            # More liquidity near best price, less further away
            decay_factor = self.DEPTH_DECAY_RATE ** i
            level_liquidity = total_liquidity * decay_factor * (1 - self.DEPTH_DECAY_RATE)

            # Add some randomness
            level_liquidity *= random.uniform(0.7, 1.3)
            level_liquidity = min(level_liquidity, remaining_liquidity)

            if level_liquidity > 0:
                # Convert dollar liquidity to quantity
                quantity = level_liquidity / price if price > 0 else 0

                levels.append(OrderBookLevel(price=round(price, 4), size=quantity))
                remaining_liquidity -= level_liquidity

        return levels

    def walk_orderbook(
        self,
        orderbook: SimulatedOrderBook,
        side: str,
        quantity: float
    ) -> Tuple[List[Fill], float, float]:
        """
        Walk the order book to fill an order.

        Args:
            orderbook: The order book to walk
            side: "BUY" or "SELL"
            quantity: Number of units to fill

        Returns:
            Tuple of (fills, average_price, unfilled_quantity)
        """
        order_side = OrderSide(side.upper())

        # Select correct side of book
        # BUY orders match against asks (take liquidity from sellers)
        # SELL orders match against bids (take liquidity from buyers)
        if order_side == OrderSide.BUY:
            levels = orderbook.asks
        else:
            levels = orderbook.bids

        fills = []
        remaining_quantity = quantity
        total_cost = 0

        for level in levels:
            if remaining_quantity <= 0:
                break

            # How much can we fill at this level?
            fill_quantity = min(remaining_quantity, level.size)

            if fill_quantity > 0:
                fills.append(Fill(
                    price=level.price,
                    quantity=fill_quantity,
                    is_partial=(remaining_quantity > level.size)
                ))
                total_cost += fill_quantity * level.price
                remaining_quantity -= fill_quantity

        filled_quantity = quantity - remaining_quantity
        average_price = total_cost / filled_quantity if filled_quantity > 0 else 0

        return fills, average_price, remaining_quantity

    def estimate_execution_price(
        self,
        orderbook: SimulatedOrderBook,
        side: str,
        quantity: float
    ) -> ExecutionResult:
        """
        Estimate execution price and details for an order.

        Args:
            orderbook: The order book
            side: "BUY" or "SELL"
            quantity: Number of units to trade

        Returns:
            ExecutionResult with complete execution details
        """
        fills, avg_price, unfilled = self.walk_orderbook(orderbook, side, quantity)

        # Calculate slippage
        if fills:
            # Slippage is difference between execution price and mid price
            slippage = abs(avg_price - orderbook.mid_price) / orderbook.mid_price
            slippage_bps = slippage * 10000
        else:
            slippage_bps = 0

        total_quantity = quantity - unfilled
        total_cost = sum(f.value for f in fills)

        return ExecutionResult(
            fills=fills,
            total_quantity=total_quantity,
            average_price=avg_price,
            total_cost=total_cost,
            slippage_bps=slippage_bps,
            unfilled_quantity=unfilled
        )


class GammaOrderBookAdapter:
    """
    Adapter to fetch and convert real order book data from Gamma/CLOB API.

    Falls back to synthetic order book generation when real data unavailable.
    """

    def __init__(self, simulator: OrderBookSimulator = None):
        """
        Initialize the adapter.

        Args:
            simulator: OrderBookSimulator for fallback synthetic generation
        """
        self.simulator = simulator or OrderBookSimulator()
        self._gamma_client = None

    @property
    def gamma_client(self):
        """Lazy load Gamma client."""
        if self._gamma_client is None:
            try:
                from agents.polymarket.gamma import GammaMarketClient
                self._gamma_client = GammaMarketClient()
            except ImportError:
                self._gamma_client = None
        return self._gamma_client

    def get_orderbook(
        self,
        token_id: str = None,
        mid_price: float = None,
        liquidity: float = None
    ) -> SimulatedOrderBook:
        """
        Get order book for a token, using real data when available.

        Args:
            token_id: The token ID to fetch order book for
            mid_price: Fallback mid price if no real data
            liquidity: Fallback liquidity estimate

        Returns:
            SimulatedOrderBook (real or synthetic)
        """
        # For now, always use synthetic
        # TODO: Implement real order book fetching from CLOB API
        if mid_price is None:
            mid_price = 0.5
        if liquidity is None:
            liquidity = 5000

        return self.simulator.generate_synthetic_orderbook(
            mid_price=mid_price,
            total_liquidity=liquidity
        )

    def get_market_conditions_from_orderbook(
        self,
        orderbook: SimulatedOrderBook,
        volume_24h: float = 10000
    ):
        """
        Convert order book to MarketConditions for FillSimulator.

        Args:
            orderbook: The order book
            volume_24h: 24-hour trading volume

        Returns:
            MarketConditions object
        """
        from agents.application.fill_simulator import MarketConditions

        return MarketConditions(
            mid_price=orderbook.mid_price,
            bid_price=orderbook.best_bid,
            ask_price=orderbook.best_ask,
            spread=orderbook.spread,
            liquidity=min(orderbook.total_bid_liquidity, orderbook.total_ask_liquidity),
            volume_24h=volume_24h
        )
