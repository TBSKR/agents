"""
Spread Model - Dynamic bid-ask spread calculation for realistic market simulation.

Models market spread based on:
- Liquidity depth
- Trading volume
- Order size impact
- Time of day effects
- Market volatility
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional
import math


@dataclass
class SpreadFactors:
    """Breakdown of factors contributing to the spread."""
    base_spread: float
    liquidity_factor: float
    size_factor: float
    volatility_factor: float
    time_factor: float
    total_spread: float


class SpreadModel:
    """
    Dynamic spread calculation based on market conditions.

    The spread model accounts for:
    1. Base spread - minimum spread for the market
    2. Liquidity - less liquidity = wider spreads
    3. Order size - larger orders widen the effective spread
    4. Volatility - higher volatility = wider spreads
    5. Time of day - off-hours may have wider spreads
    """

    # Base spread configurations
    BASE_SPREAD = 0.005  # 0.5% base spread
    MIN_SPREAD = 0.001  # 0.1% minimum spread
    MAX_SPREAD = 0.10  # 10% maximum spread

    # Factor weights
    LIQUIDITY_WEIGHT = 0.3
    SIZE_WEIGHT = 0.2
    VOLATILITY_WEIGHT = 0.3
    TIME_WEIGHT = 0.1

    # Reference values
    REFERENCE_LIQUIDITY = 10000  # $10,000 reference liquidity
    REFERENCE_VOLUME = 50000  # $50,000 reference 24h volume

    def __init__(
        self,
        base_spread: float = None,
        min_spread: float = None,
        max_spread: float = None
    ):
        """
        Initialize the spread model.

        Args:
            base_spread: Base spread as decimal (e.g., 0.005 for 0.5%)
            min_spread: Minimum allowable spread
            max_spread: Maximum allowable spread
        """
        self.base_spread = base_spread or self.BASE_SPREAD
        self.min_spread = min_spread or self.MIN_SPREAD
        self.max_spread = max_spread or self.MAX_SPREAD

    def calculate_liquidity_factor(self, liquidity: float) -> float:
        """
        Calculate spread adjustment based on liquidity.

        Lower liquidity = higher factor = wider spread.

        Args:
            liquidity: Available liquidity in dollars

        Returns:
            Multiplier for spread (1.0 = no adjustment)
        """
        if liquidity <= 0:
            return 3.0  # Maximum penalty for no liquidity

        # Inverse relationship with liquidity
        # Reference liquidity gives factor of 1.0
        ratio = self.REFERENCE_LIQUIDITY / liquidity

        # Use log scaling to prevent extreme values
        factor = 1 + math.log(max(ratio, 0.1)) * 0.3

        return max(0.5, min(factor, 3.0))

    def calculate_size_factor(
        self,
        order_size: float,
        liquidity: float
    ) -> float:
        """
        Calculate spread adjustment based on order size relative to liquidity.

        Larger orders relative to liquidity = wider effective spread.

        Args:
            order_size: Order size in dollars
            liquidity: Available liquidity in dollars

        Returns:
            Multiplier for spread (1.0 = no adjustment)
        """
        if liquidity <= 0:
            return 2.0

        # Order as percentage of liquidity
        size_ratio = order_size / liquidity

        if size_ratio < 0.01:  # < 1% of liquidity
            return 1.0
        elif size_ratio < 0.05:  # 1-5% of liquidity
            return 1.0 + size_ratio * 5
        elif size_ratio < 0.20:  # 5-20% of liquidity
            return 1.25 + (size_ratio - 0.05) * 3
        else:  # > 20% of liquidity
            return 1.7 + (size_ratio - 0.20) * 2

    def calculate_volatility_factor(self, volatility: float) -> float:
        """
        Calculate spread adjustment based on market volatility.

        Higher volatility = wider spreads to compensate for risk.

        Args:
            volatility: Price volatility as decimal (e.g., 0.05 for 5%)

        Returns:
            Multiplier for spread (1.0 = no adjustment)
        """
        if volatility <= 0:
            return 1.0

        # Linear relationship with volatility
        # 5% volatility = 1.5x spread
        factor = 1 + volatility * 10

        return max(1.0, min(factor, 3.0))

    def calculate_time_factor(self, timestamp: Optional[datetime] = None) -> float:
        """
        Calculate spread adjustment based on time of day.

        Market hours have tighter spreads, off-hours are wider.

        Args:
            timestamp: Time to evaluate (defaults to now)

        Returns:
            Multiplier for spread (1.0 = no adjustment)
        """
        if timestamp is None:
            timestamp = datetime.now()

        hour = timestamp.hour

        # Peak hours (9 AM - 5 PM EST) have tighter spreads
        # Note: This is a simplified model
        if 9 <= hour <= 17:
            return 1.0
        elif 6 <= hour < 9 or 17 < hour <= 21:
            return 1.1  # Early morning / evening
        else:
            return 1.2  # Late night / early morning

    def calculate_spread(
        self,
        liquidity: float,
        volume_24h: float = None,
        order_size: float = 0,
        volatility: float = 0,
        timestamp: Optional[datetime] = None
    ) -> float:
        """
        Calculate the total spread considering all factors.

        Args:
            liquidity: Available liquidity at best price
            volume_24h: 24-hour trading volume (optional, used for validation)
            order_size: Size of the order being placed
            volatility: Recent price volatility
            timestamp: Time of the trade

        Returns:
            Total spread as decimal (e.g., 0.02 for 2%)
        """
        # Calculate individual factors
        liquidity_factor = self.calculate_liquidity_factor(liquidity)
        size_factor = self.calculate_size_factor(order_size, liquidity)
        volatility_factor = self.calculate_volatility_factor(volatility)
        time_factor = self.calculate_time_factor(timestamp)

        # Weighted combination
        # Base spread is adjusted by each factor
        combined_factor = (
            1.0 +
            (liquidity_factor - 1) * self.LIQUIDITY_WEIGHT +
            (size_factor - 1) * self.SIZE_WEIGHT +
            (volatility_factor - 1) * self.VOLATILITY_WEIGHT +
            (time_factor - 1) * self.TIME_WEIGHT
        )

        spread = self.base_spread * combined_factor

        # Clamp to min/max
        spread = max(self.min_spread, min(spread, self.max_spread))

        return spread

    def calculate_spread_detailed(
        self,
        liquidity: float,
        volume_24h: float = None,
        order_size: float = 0,
        volatility: float = 0,
        timestamp: Optional[datetime] = None
    ) -> SpreadFactors:
        """
        Calculate spread with detailed breakdown of contributing factors.

        Returns:
            SpreadFactors with breakdown of each component
        """
        liquidity_factor = self.calculate_liquidity_factor(liquidity)
        size_factor = self.calculate_size_factor(order_size, liquidity)
        volatility_factor = self.calculate_volatility_factor(volatility)
        time_factor = self.calculate_time_factor(timestamp)

        total_spread = self.calculate_spread(
            liquidity=liquidity,
            volume_24h=volume_24h,
            order_size=order_size,
            volatility=volatility,
            timestamp=timestamp
        )

        return SpreadFactors(
            base_spread=self.base_spread,
            liquidity_factor=liquidity_factor,
            size_factor=size_factor,
            volatility_factor=volatility_factor,
            time_factor=time_factor,
            total_spread=total_spread
        )

    def get_bid_ask_prices(
        self,
        mid_price: float,
        liquidity: float,
        volume_24h: float = None,
        order_size: float = 0,
        volatility: float = 0,
        timestamp: Optional[datetime] = None
    ) -> tuple[float, float]:
        """
        Calculate bid and ask prices from mid price.

        Args:
            mid_price: The mid-market price
            Other args: Same as calculate_spread

        Returns:
            Tuple of (bid_price, ask_price)
        """
        spread = self.calculate_spread(
            liquidity=liquidity,
            volume_24h=volume_24h,
            order_size=order_size,
            volatility=volatility,
            timestamp=timestamp
        )

        half_spread = spread / 2
        bid_price = mid_price * (1 - half_spread)
        ask_price = mid_price * (1 + half_spread)

        return bid_price, ask_price


class PolymarketSpreadModel(SpreadModel):
    """
    Spread model specifically calibrated for Polymarket prediction markets.

    Polymarket markets tend to have:
    - Wider spreads near 0 and 1 (extreme prices)
    - Tighter spreads around 0.5 (uncertain outcomes)
    - Higher liquidity on popular markets
    """

    # Polymarket-specific defaults
    BASE_SPREAD = 0.01  # 1% base spread (prediction markets are less liquid)
    MIN_SPREAD = 0.002  # 0.2% minimum
    MAX_SPREAD = 0.15  # 15% maximum

    def calculate_price_factor(self, price: float) -> float:
        """
        Calculate spread adjustment based on the probability price.

        Spreads are wider near 0 and 1, tighter near 0.5.

        Args:
            price: Market price (0-1 representing probability)

        Returns:
            Multiplier for spread
        """
        # Distance from 0.5 (center)
        distance_from_center = abs(price - 0.5)

        # Parabolic curve: wider at extremes
        # At 0.5: factor = 1.0
        # At 0 or 1: factor = 2.0
        factor = 1 + distance_from_center * 2

        return factor

    def calculate_spread(
        self,
        liquidity: float,
        volume_24h: float = None,
        order_size: float = 0,
        volatility: float = 0,
        timestamp: Optional[datetime] = None,
        price: float = 0.5
    ) -> float:
        """
        Calculate spread with Polymarket-specific adjustments.

        Args:
            price: Current market price (0-1)
            Other args: Same as parent class

        Returns:
            Total spread as decimal
        """
        # Get base spread from parent
        base_spread = super().calculate_spread(
            liquidity=liquidity,
            volume_24h=volume_24h,
            order_size=order_size,
            volatility=volatility,
            timestamp=timestamp
        )

        # Apply price factor
        price_factor = self.calculate_price_factor(price)
        adjusted_spread = base_spread * price_factor

        # Clamp to limits
        return max(self.min_spread, min(adjusted_spread, self.max_spread))
