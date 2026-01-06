"""
Market Impact Model - Estimates the price impact of trades.

This module provides:
- Temporary impact estimation (immediate price movement)
- Permanent impact estimation (lasting price shift)
- Optimal execution recommendations
- Impact-adjusted cost calculations
"""

from dataclasses import dataclass
from typing import Optional
import math


@dataclass
class MarketImpactEstimate:
    """Complete market impact estimate for a trade."""
    temporary_impact_bps: float  # Temporary impact in basis points
    permanent_impact_bps: float  # Permanent impact in basis points
    total_impact_bps: float  # Combined impact
    expected_slippage_pct: float  # Expected slippage as percentage
    impact_cost_dollars: float  # Estimated impact cost in dollars
    recommended_slice_size: float  # Recommended order slice size
    optimal_execution_time_minutes: float  # Optimal execution time
    confidence: float  # Confidence in estimate (0-1)


class MarketImpactModel:
    """
    Models temporary and permanent market impact of trades.

    Based on the Square Root Law of market impact:
    Impact ~ sigma * sqrt(Q / V)

    Where:
    - sigma = volatility
    - Q = order quantity
    - V = average daily volume
    """

    # Model parameters
    TEMP_IMPACT_COEFFICIENT = 0.1  # Temporary impact coefficient
    PERM_IMPACT_COEFFICIENT = 0.05  # Permanent impact coefficient (typically smaller)
    DEFAULT_VOLATILITY = 0.02  # 2% default daily volatility

    # Execution parameters
    PARTICIPATION_RATE = 0.1  # Don't exceed 10% of market volume
    MIN_SLICE_SIZE = 10  # Minimum slice size in dollars

    def __init__(
        self,
        temp_impact_coef: float = None,
        perm_impact_coef: float = None,
        default_volatility: float = None
    ):
        """
        Initialize the market impact model.

        Args:
            temp_impact_coef: Coefficient for temporary impact
            perm_impact_coef: Coefficient for permanent impact
            default_volatility: Default volatility to use when not provided
        """
        self.temp_impact_coef = temp_impact_coef or self.TEMP_IMPACT_COEFFICIENT
        self.perm_impact_coef = perm_impact_coef or self.PERM_IMPACT_COEFFICIENT
        self.default_volatility = default_volatility or self.DEFAULT_VOLATILITY

    def calculate_temporary_impact(
        self,
        order_size: float,
        avg_daily_volume: float,
        volatility: float = None
    ) -> float:
        """
        Calculate temporary market impact.

        Temporary impact is the immediate price movement caused by the order,
        which typically reverts partially after execution.

        Args:
            order_size: Order size in dollars
            avg_daily_volume: Average daily trading volume in dollars
            volatility: Price volatility (daily) as decimal

        Returns:
            Temporary impact in basis points
        """
        volatility = volatility or self.default_volatility

        if avg_daily_volume <= 0:
            return 500  # Maximum impact for illiquid markets

        # Square root law: impact ~ sigma * sqrt(Q/V)
        participation = order_size / avg_daily_volume
        impact = self.temp_impact_coef * volatility * math.sqrt(participation)

        # Convert to basis points
        impact_bps = impact * 10000

        return min(impact_bps, 500)  # Cap at 5%

    def calculate_permanent_impact(
        self,
        order_size: float,
        avg_daily_volume: float
    ) -> float:
        """
        Calculate permanent market impact.

        Permanent impact is the lasting price shift after the order,
        representing information leakage and price discovery.

        Args:
            order_size: Order size in dollars
            avg_daily_volume: Average daily trading volume in dollars

        Returns:
            Permanent impact in basis points
        """
        if avg_daily_volume <= 0:
            return 200  # Maximum permanent impact

        # Linear relationship with participation
        participation = order_size / avg_daily_volume
        impact = self.perm_impact_coef * participation

        # Convert to basis points
        impact_bps = impact * 10000

        return min(impact_bps, 200)  # Cap at 2%

    def calculate_optimal_slice_size(
        self,
        order_size: float,
        avg_daily_volume: float,
        max_participation_rate: float = None
    ) -> float:
        """
        Calculate optimal slice size for order execution.

        Larger orders should be sliced to minimize market impact.

        Args:
            order_size: Total order size in dollars
            avg_daily_volume: Average daily volume in dollars
            max_participation_rate: Maximum participation rate (0-1)

        Returns:
            Recommended slice size in dollars
        """
        max_rate = max_participation_rate or self.PARTICIPATION_RATE

        # Maximum slice based on participation rate
        max_slice = avg_daily_volume * max_rate

        # Optimal slice is smaller of max_slice and order_size
        slice_size = min(max_slice, order_size)

        # Enforce minimum slice size
        slice_size = max(slice_size, self.MIN_SLICE_SIZE)

        return slice_size

    def calculate_optimal_execution_time(
        self,
        order_size: float,
        avg_daily_volume: float,
        slice_size: float = None
    ) -> float:
        """
        Calculate optimal execution time in minutes.

        Args:
            order_size: Total order size in dollars
            avg_daily_volume: Average daily volume in dollars
            slice_size: Slice size (if already calculated)

        Returns:
            Optimal execution time in minutes
        """
        if slice_size is None:
            slice_size = self.calculate_optimal_slice_size(order_size, avg_daily_volume)

        # Number of slices needed
        num_slices = math.ceil(order_size / slice_size)

        if num_slices <= 1:
            return 0  # Execute immediately

        # Assume trading happens over 8 hours, volume is uniform
        trading_minutes = 8 * 60
        volume_per_minute = avg_daily_volume / trading_minutes

        # Time between slices should allow volume to absorb impact
        time_per_slice = (slice_size / volume_per_minute) * 2  # 2x buffer

        return num_slices * time_per_slice

    def estimate_total_impact(
        self,
        order_size: float,
        avg_daily_volume: float,
        volatility: float = None,
        current_price: float = None
    ) -> MarketImpactEstimate:
        """
        Calculate complete market impact estimate.

        Args:
            order_size: Order size in dollars
            avg_daily_volume: Average daily volume in dollars
            volatility: Price volatility (optional)
            current_price: Current market price (optional, for cost calc)

        Returns:
            MarketImpactEstimate with full breakdown
        """
        temp_impact = self.calculate_temporary_impact(
            order_size, avg_daily_volume, volatility
        )
        perm_impact = self.calculate_permanent_impact(order_size, avg_daily_volume)

        total_impact = temp_impact + perm_impact
        slippage_pct = total_impact / 100  # Convert bps to percent

        # Calculate dollar cost
        if current_price and current_price > 0:
            impact_cost = order_size * (slippage_pct / 100)
        else:
            impact_cost = 0

        slice_size = self.calculate_optimal_slice_size(order_size, avg_daily_volume)
        exec_time = self.calculate_optimal_execution_time(
            order_size, avg_daily_volume, slice_size
        )

        # Confidence based on order size relative to volume
        participation = order_size / max(avg_daily_volume, 1)
        if participation < 0.01:
            confidence = 0.9  # High confidence for small orders
        elif participation < 0.05:
            confidence = 0.7
        elif participation < 0.10:
            confidence = 0.5
        else:
            confidence = 0.3  # Low confidence for large orders

        return MarketImpactEstimate(
            temporary_impact_bps=temp_impact,
            permanent_impact_bps=perm_impact,
            total_impact_bps=total_impact,
            expected_slippage_pct=slippage_pct,
            impact_cost_dollars=impact_cost,
            recommended_slice_size=slice_size,
            optimal_execution_time_minutes=exec_time,
            confidence=confidence
        )

    def should_slice_order(
        self,
        order_size: float,
        avg_daily_volume: float,
        impact_threshold_bps: float = 50
    ) -> bool:
        """
        Determine if an order should be sliced for execution.

        Args:
            order_size: Order size in dollars
            avg_daily_volume: Average daily volume
            impact_threshold_bps: Impact threshold for slicing (default 50 bps)

        Returns:
            True if order should be sliced
        """
        temp_impact = self.calculate_temporary_impact(order_size, avg_daily_volume)
        return temp_impact > impact_threshold_bps

    def adjust_order_for_impact(
        self,
        target_quantity: float,
        current_price: float,
        avg_daily_volume: float,
        volatility: float = None,
        max_impact_bps: float = 100
    ) -> tuple[float, float]:
        """
        Adjust order size to stay within impact limits.

        Args:
            target_quantity: Desired quantity
            current_price: Current market price
            avg_daily_volume: Average daily volume
            volatility: Market volatility
            max_impact_bps: Maximum acceptable impact in basis points

        Returns:
            Tuple of (adjusted_quantity, expected_impact_bps)
        """
        order_size = target_quantity * current_price

        # Check current impact
        impact = self.calculate_temporary_impact(order_size, avg_daily_volume, volatility)

        if impact <= max_impact_bps:
            return target_quantity, impact

        # Binary search for maximum acceptable size
        low, high = 0, target_quantity
        best_quantity = 0

        for _ in range(10):  # 10 iterations for precision
            mid = (low + high) / 2
            mid_size = mid * current_price
            mid_impact = self.calculate_temporary_impact(mid_size, avg_daily_volume, volatility)

            if mid_impact <= max_impact_bps:
                best_quantity = mid
                low = mid
            else:
                high = mid

        final_size = best_quantity * current_price
        final_impact = self.calculate_temporary_impact(final_size, avg_daily_volume, volatility)

        return best_quantity, final_impact


class PolymarketImpactModel(MarketImpactModel):
    """
    Market impact model calibrated for Polymarket prediction markets.

    Polymarket has some unique characteristics:
    - Generally lower liquidity than traditional markets
    - Binary outcomes create natural price boundaries
    - Liquidity varies significantly by market popularity
    """

    # Polymarket-specific parameters
    TEMP_IMPACT_COEFFICIENT = 0.15  # Higher due to lower liquidity
    PERM_IMPACT_COEFFICIENT = 0.08
    DEFAULT_VOLATILITY = 0.05  # Prediction markets can be more volatile

    def __init__(self):
        """Initialize with Polymarket-specific parameters."""
        super().__init__(
            temp_impact_coef=self.TEMP_IMPACT_COEFFICIENT,
            perm_impact_coef=self.PERM_IMPACT_COEFFICIENT,
            default_volatility=self.DEFAULT_VOLATILITY
        )

    def calculate_temporary_impact(
        self,
        order_size: float,
        avg_daily_volume: float,
        volatility: float = None,
        price: float = None
    ) -> float:
        """
        Calculate temporary impact with Polymarket adjustments.

        Args:
            order_size: Order size in dollars
            avg_daily_volume: Average daily volume
            volatility: Price volatility
            price: Current price (0-1) for boundary effects

        Returns:
            Temporary impact in basis points
        """
        # Base calculation
        base_impact = super().calculate_temporary_impact(
            order_size, avg_daily_volume, volatility
        )

        # Adjust for price boundaries
        # Impact is higher near 0 and 1 where liquidity is typically lower
        if price is not None:
            boundary_factor = self._calculate_boundary_factor(price)
            base_impact *= boundary_factor

        return min(base_impact, 500)

    def _calculate_boundary_factor(self, price: float) -> float:
        """
        Calculate impact multiplier based on price proximity to boundaries.

        Impact is higher near 0 and 1 due to reduced liquidity.
        """
        # Distance from nearest boundary
        distance_from_boundary = min(price, 1 - price)

        if distance_from_boundary < 0.05:
            return 2.0  # 2x impact very close to boundaries
        elif distance_from_boundary < 0.1:
            return 1.5
        elif distance_from_boundary < 0.2:
            return 1.2
        else:
            return 1.0
