"""
Fill Simulator - Realistic order execution simulation for paper trading.

This module provides realistic fill simulation including:
- Variable slippage based on order size and liquidity
- Partial fills with order book walking
- Market impact modeling
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Tuple
from enum import Enum
import random
import math


class OrderSide(Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(Enum):
    MARKET = "market"
    LIMIT = "limit"


@dataclass
class Fill:
    """Represents a single fill at a specific price level."""
    price: float
    quantity: float
    timestamp: datetime = field(default_factory=datetime.now)
    is_partial: bool = False

    @property
    def value(self) -> float:
        return self.price * self.quantity


@dataclass
class ExecutionResult:
    """Complete result of an order execution attempt."""
    fills: List[Fill]
    total_quantity: float
    average_price: float
    total_cost: float
    slippage_bps: float  # Slippage in basis points
    unfilled_quantity: float
    execution_time: datetime = field(default_factory=datetime.now)

    @property
    def is_complete(self) -> bool:
        return self.unfilled_quantity < 0.0001

    @property
    def is_partial(self) -> bool:
        return not self.is_complete and self.total_quantity > 0

    @property
    def fill_rate(self) -> float:
        """Percentage of order that was filled."""
        total_requested = self.total_quantity + self.unfilled_quantity
        if total_requested == 0:
            return 0.0
        return (self.total_quantity / total_requested) * 100


@dataclass
class MarketConditions:
    """Current market conditions affecting execution."""
    mid_price: float
    bid_price: float
    ask_price: float
    spread: float  # As a decimal (e.g., 0.02 for 2%)
    liquidity: float  # Estimated $ liquidity at best price
    volume_24h: float  # 24h trading volume
    volatility: float = 0.0  # Recent price volatility


class FillSimulator:
    """
    Simulates realistic order fills for paper trading.

    Key features:
    - Dynamic slippage based on order size relative to liquidity
    - Partial fill simulation for large orders
    - Spread-aware execution
    - Market impact modeling
    """

    # Configuration constants
    BASE_SLIPPAGE_BPS = 10  # 0.1% base slippage (10 basis points)
    MAX_SLIPPAGE_BPS = 500  # 5% maximum slippage
    PARTIAL_FILL_PROBABILITY = 0.15  # 15% chance of partial fill for small orders
    LARGE_ORDER_THRESHOLD = 0.1  # Order is "large" if > 10% of liquidity

    def __init__(
        self,
        base_slippage_bps: int = None,
        max_slippage_bps: int = None,
        enable_partial_fills: bool = True,
        random_seed: int = None
    ):
        """
        Initialize the fill simulator.

        Args:
            base_slippage_bps: Base slippage in basis points
            max_slippage_bps: Maximum allowable slippage
            enable_partial_fills: Whether to simulate partial fills
            random_seed: Seed for reproducible randomness (useful for testing)
        """
        self.base_slippage_bps = base_slippage_bps or self.BASE_SLIPPAGE_BPS
        self.max_slippage_bps = max_slippage_bps or self.MAX_SLIPPAGE_BPS
        self.enable_partial_fills = enable_partial_fills

        if random_seed is not None:
            random.seed(random_seed)

    def calculate_slippage(
        self,
        order_size: float,
        side: OrderSide,
        conditions: MarketConditions
    ) -> float:
        """
        Calculate expected slippage based on order characteristics.

        Slippage factors:
        1. Base slippage (fixed minimum)
        2. Size impact (larger orders = more slippage)
        3. Liquidity adjustment (less liquidity = more slippage)
        4. Spread component (crossing the spread)

        Returns:
            Slippage as a decimal (e.g., 0.005 for 0.5%)
        """
        # Base slippage
        slippage_bps = self.base_slippage_bps

        # Size impact: increases with order size relative to liquidity
        if conditions.liquidity > 0:
            size_ratio = order_size / conditions.liquidity
            # Square root function for diminishing but increasing impact
            size_impact_bps = 50 * math.sqrt(size_ratio)  # Up to ~50 bps for equal-to-liquidity orders
            slippage_bps += size_impact_bps

        # Liquidity adjustment: penalize low liquidity markets
        if conditions.liquidity < 1000:
            liquidity_penalty_bps = (1000 - conditions.liquidity) / 1000 * 30  # Up to 30 bps
            slippage_bps += liquidity_penalty_bps

        # Spread component: add half the spread (you pay to cross it)
        spread_bps = conditions.spread * 10000 / 2
        slippage_bps += spread_bps

        # Volatility adjustment
        if conditions.volatility > 0:
            volatility_bps = conditions.volatility * 100  # 1% volatility = 100 bps
            slippage_bps += volatility_bps * 0.1  # 10% of volatility

        # Cap at maximum
        slippage_bps = min(slippage_bps, self.max_slippage_bps)

        # Add small random variation (+/- 20%)
        variation = random.uniform(0.8, 1.2)
        slippage_bps *= variation

        return slippage_bps / 10000  # Convert to decimal

    def calculate_execution_price(
        self,
        side: OrderSide,
        base_price: float,
        slippage: float
    ) -> float:
        """
        Calculate the execution price after slippage.

        For BUY orders: price increases (you pay more)
        For SELL orders: price decreases (you receive less)
        """
        if side == OrderSide.BUY:
            return base_price * (1 + slippage)
        else:
            return base_price * (1 - slippage)

    def should_partially_fill(
        self,
        order_size: float,
        conditions: MarketConditions
    ) -> Tuple[bool, float]:
        """
        Determine if an order should partially fill and by how much.

        Returns:
            Tuple of (should_partial_fill, fill_percentage)
        """
        if not self.enable_partial_fills:
            return False, 1.0

        # Large orders relative to liquidity are more likely to partial fill
        size_ratio = order_size / max(conditions.liquidity, 1)

        if size_ratio > self.LARGE_ORDER_THRESHOLD:
            # High probability of partial fill for large orders
            partial_prob = min(0.8, size_ratio * 2)
            if random.random() < partial_prob:
                # Fill between 50-95% of the order
                fill_pct = random.uniform(0.5, 0.95)
                return True, fill_pct

        # Small random chance of partial fill for any order
        if random.random() < self.PARTIAL_FILL_PROBABILITY:
            fill_pct = random.uniform(0.7, 0.99)
            return True, fill_pct

        return False, 1.0

    def simulate_market_order(
        self,
        side: str,
        quantity: float,
        conditions: MarketConditions
    ) -> ExecutionResult:
        """
        Simulate a market order execution.

        Args:
            side: "BUY" or "SELL"
            quantity: Number of shares/contracts to trade
            conditions: Current market conditions

        Returns:
            ExecutionResult with fill details
        """
        order_side = OrderSide(side.upper())

        # Determine base price (bid for sells, ask for buys)
        if order_side == OrderSide.BUY:
            base_price = conditions.ask_price
        else:
            base_price = conditions.bid_price

        # Calculate order value for slippage calculation
        order_value = quantity * base_price

        # Calculate slippage
        slippage = self.calculate_slippage(order_value, order_side, conditions)

        # Check for partial fill
        is_partial, fill_pct = self.should_partially_fill(order_value, conditions)

        # Calculate execution details
        filled_quantity = quantity * fill_pct
        execution_price = self.calculate_execution_price(order_side, base_price, slippage)

        # Create fills (could be multiple for large orders, simplified here)
        fills = []
        if filled_quantity > 0:
            fills.append(Fill(
                price=execution_price,
                quantity=filled_quantity,
                is_partial=is_partial
            ))

        total_cost = filled_quantity * execution_price
        slippage_bps = slippage * 10000

        return ExecutionResult(
            fills=fills,
            total_quantity=filled_quantity,
            average_price=execution_price if filled_quantity > 0 else 0,
            total_cost=total_cost,
            slippage_bps=slippage_bps,
            unfilled_quantity=quantity - filled_quantity
        )

    def simulate_limit_order(
        self,
        side: str,
        quantity: float,
        limit_price: float,
        conditions: MarketConditions,
        time_in_force_seconds: int = 3600
    ) -> ExecutionResult:
        """
        Simulate a limit order execution.

        Limit orders may not fill at all if the price doesn't reach the limit.

        Args:
            side: "BUY" or "SELL"
            quantity: Number of shares/contracts to trade
            limit_price: Maximum price for buys, minimum for sells
            conditions: Current market conditions
            time_in_force_seconds: How long the order is valid

        Returns:
            ExecutionResult with fill details
        """
        order_side = OrderSide(side.upper())

        # Check if limit price is marketable
        if order_side == OrderSide.BUY:
            is_marketable = limit_price >= conditions.ask_price
            best_price = conditions.ask_price
        else:
            is_marketable = limit_price <= conditions.bid_price
            best_price = conditions.bid_price

        if is_marketable:
            # Execute immediately at better price
            execution_price = min(limit_price, best_price) if order_side == OrderSide.BUY else max(limit_price, best_price)

            # Still apply some slippage but capped at limit
            order_value = quantity * execution_price
            slippage = self.calculate_slippage(order_value, order_side, conditions)
            slippage_price = self.calculate_execution_price(order_side, best_price, slippage)

            # For buys, take the minimum of slippage price and limit
            # For sells, take the maximum of slippage price and limit
            if order_side == OrderSide.BUY:
                final_price = min(slippage_price, limit_price)
            else:
                final_price = max(slippage_price, limit_price)

            # Check for partial fill
            is_partial, fill_pct = self.should_partially_fill(order_value, conditions)
            filled_quantity = quantity * fill_pct

            fills = [Fill(
                price=final_price,
                quantity=filled_quantity,
                is_partial=is_partial
            )] if filled_quantity > 0 else []

            actual_slippage = abs(final_price - conditions.mid_price) / conditions.mid_price

            return ExecutionResult(
                fills=fills,
                total_quantity=filled_quantity,
                average_price=final_price if filled_quantity > 0 else 0,
                total_cost=filled_quantity * final_price,
                slippage_bps=actual_slippage * 10000,
                unfilled_quantity=quantity - filled_quantity
            )

        else:
            # Order rests in book - simulate probability of fill based on distance from market
            price_distance = abs(limit_price - conditions.mid_price) / conditions.mid_price

            # Probability decreases with distance from market
            # and increases with time in force
            base_fill_prob = max(0, 1 - price_distance * 10)  # 10% away = 0% prob
            time_factor = min(1, time_in_force_seconds / 3600)  # 1 hour = full time factor
            fill_prob = base_fill_prob * time_factor * 0.5  # Max 50% fill prob for resting orders

            if random.random() < fill_prob:
                # Order fills at limit price
                filled_quantity = quantity * random.uniform(0.5, 1.0)

                fills = [Fill(
                    price=limit_price,
                    quantity=filled_quantity,
                    is_partial=filled_quantity < quantity
                )]

                return ExecutionResult(
                    fills=fills,
                    total_quantity=filled_quantity,
                    average_price=limit_price,
                    total_cost=filled_quantity * limit_price,
                    slippage_bps=0,  # No slippage for limit orders
                    unfilled_quantity=quantity - filled_quantity
                )
            else:
                # Order doesn't fill
                return ExecutionResult(
                    fills=[],
                    total_quantity=0,
                    average_price=0,
                    total_cost=0,
                    slippage_bps=0,
                    unfilled_quantity=quantity
                )


def create_market_conditions_from_price(
    price: float,
    liquidity: float = 5000,
    volume_24h: float = 10000,
    spread_pct: float = 0.02
) -> MarketConditions:
    """
    Helper to create MarketConditions from a simple price.

    Args:
        price: Mid-market price
        liquidity: Estimated liquidity at best price
        volume_24h: 24-hour trading volume
        spread_pct: Bid-ask spread as percentage (e.g., 0.02 for 2%)

    Returns:
        MarketConditions object
    """
    half_spread = spread_pct / 2
    return MarketConditions(
        mid_price=price,
        bid_price=price * (1 - half_spread),
        ask_price=price * (1 + half_spread),
        spread=spread_pct,
        liquidity=liquidity,
        volume_24h=volume_24h
    )
