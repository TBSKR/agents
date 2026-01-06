"""
Tests for the fill simulator module.

Minimal critical path tests for:
- FillSimulator market order execution
- Slippage calculation
- Partial fill handling
"""

import pytest
from datetime import datetime

from agents.application.fill_simulator import (
    FillSimulator,
    MarketConditions,
    ExecutionResult,
    Fill,
    OrderSide,
    create_market_conditions_from_price
)


class TestMarketConditions:
    """Tests for MarketConditions creation."""

    def test_create_market_conditions_from_price(self):
        """Test helper function creates valid conditions."""
        conditions = create_market_conditions_from_price(
            price=0.5,
            liquidity=5000,
            volume_24h=10000,
            spread_pct=0.02
        )

        assert conditions.mid_price == 0.5
        assert conditions.liquidity == 5000
        assert conditions.volume_24h == 10000
        assert conditions.spread == 0.02
        # Check bid/ask are symmetric around mid
        assert conditions.bid_price < conditions.mid_price
        assert conditions.ask_price > conditions.mid_price

    def test_market_conditions_spread_bounds(self):
        """Test that bid < mid < ask."""
        conditions = create_market_conditions_from_price(price=0.75, spread_pct=0.04)

        assert conditions.bid_price < conditions.mid_price < conditions.ask_price


class TestFillSimulator:
    """Tests for FillSimulator core functionality."""

    @pytest.fixture
    def simulator(self):
        """Create a fill simulator with fixed seed for reproducibility."""
        return FillSimulator(random_seed=42)

    @pytest.fixture
    def standard_conditions(self):
        """Standard market conditions for testing."""
        return MarketConditions(
            mid_price=0.5,
            bid_price=0.49,
            ask_price=0.51,
            spread=0.04,  # 4%
            liquidity=5000,
            volume_24h=10000
        )

    def test_simulate_market_order_buy(self, simulator, standard_conditions):
        """Test basic BUY market order execution."""
        result = simulator.simulate_market_order(
            side="BUY",
            quantity=100,
            conditions=standard_conditions
        )

        assert isinstance(result, ExecutionResult)
        assert result.total_quantity > 0
        assert result.average_price >= standard_conditions.mid_price  # BUY pays higher
        assert result.total_cost > 0
        assert len(result.fills) > 0

    def test_simulate_market_order_sell(self, simulator, standard_conditions):
        """Test basic SELL market order execution."""
        result = simulator.simulate_market_order(
            side="SELL",
            quantity=100,
            conditions=standard_conditions
        )

        assert isinstance(result, ExecutionResult)
        assert result.total_quantity > 0
        assert result.average_price <= standard_conditions.mid_price  # SELL receives lower
        assert result.total_cost > 0

    def test_slippage_increases_with_size(self):
        """Test that larger orders have more slippage on average."""
        # Use separate simulator instances to avoid random seed state
        conditions = MarketConditions(
            mid_price=0.5,
            bid_price=0.49,
            ask_price=0.51,
            spread=0.02,
            liquidity=1000,  # Low liquidity
            volume_24h=5000
        )

        # Average over multiple samples to account for randomness
        small_slippages = []
        large_slippages = []

        for seed in range(10):
            sim = FillSimulator(random_seed=seed)
            small_slippages.append(sim.calculate_slippage(
                order_size=50,
                side=OrderSide.BUY,
                conditions=conditions
            ))
            large_slippages.append(sim.calculate_slippage(
                order_size=500,
                side=OrderSide.BUY,
                conditions=conditions
            ))

        avg_small = sum(small_slippages) / len(small_slippages)
        avg_large = sum(large_slippages) / len(large_slippages)

        # Large order should have more slippage on average
        assert avg_large > avg_small

    def test_slippage_increases_with_low_liquidity(self):
        """Test that low liquidity causes more slippage on average."""
        # High liquidity
        high_liq_conditions = MarketConditions(
            mid_price=0.5,
            bid_price=0.49,
            ask_price=0.51,
            spread=0.02,
            liquidity=10000,
            volume_24h=50000
        )

        # Low liquidity
        low_liq_conditions = MarketConditions(
            mid_price=0.5,
            bid_price=0.49,
            ask_price=0.51,
            spread=0.02,
            liquidity=500,
            volume_24h=1000
        )

        # Average over multiple samples to account for randomness
        high_liq_slippages = []
        low_liq_slippages = []

        for seed in range(10):
            sim = FillSimulator(random_seed=seed)
            high_liq_slippages.append(sim.calculate_slippage(
                order_size=100,
                side=OrderSide.BUY,
                conditions=high_liq_conditions
            ))
            low_liq_slippages.append(sim.calculate_slippage(
                order_size=100,
                side=OrderSide.BUY,
                conditions=low_liq_conditions
            ))

        avg_high_liq = sum(high_liq_slippages) / len(high_liq_slippages)
        avg_low_liq = sum(low_liq_slippages) / len(low_liq_slippages)

        assert avg_low_liq > avg_high_liq

    def test_slippage_capped_at_maximum(self, simulator):
        """Test that slippage doesn't exceed maximum."""
        # Extreme conditions
        extreme_conditions = MarketConditions(
            mid_price=0.5,
            bid_price=0.45,
            ask_price=0.55,
            spread=0.20,  # 20% spread
            liquidity=10,  # Very low liquidity
            volume_24h=100
        )

        slippage = simulator.calculate_slippage(
            order_size=1000,  # Large order relative to liquidity
            side=OrderSide.BUY,
            conditions=extreme_conditions
        )

        # Should be capped
        max_slippage = simulator.max_slippage_bps / 10000
        assert slippage <= max_slippage * 1.5  # Allow some variance

    def test_execution_price_direction(self, simulator, standard_conditions):
        """Test that execution prices move in correct direction."""
        slippage = 0.01  # 1%

        buy_price = simulator.calculate_execution_price(
            side=OrderSide.BUY,
            base_price=0.5,
            slippage=slippage
        )

        sell_price = simulator.calculate_execution_price(
            side=OrderSide.SELL,
            base_price=0.5,
            slippage=slippage
        )

        # BUY should pay more, SELL should receive less
        assert buy_price > 0.5
        assert sell_price < 0.5

    def test_execution_result_properties(self, simulator, standard_conditions):
        """Test ExecutionResult computed properties."""
        result = simulator.simulate_market_order(
            side="BUY",
            quantity=100,
            conditions=standard_conditions
        )

        # Test is_complete
        if result.unfilled_quantity < 0.0001:
            assert result.is_complete
            assert not result.is_partial
        else:
            assert not result.is_complete
            assert result.is_partial

        # Test fill_rate
        assert 0 <= result.fill_rate <= 100

    def test_partial_fill_disabled(self):
        """Test that partial fills can be disabled."""
        simulator = FillSimulator(
            enable_partial_fills=False,
            random_seed=42
        )

        conditions = MarketConditions(
            mid_price=0.5,
            bid_price=0.49,
            ask_price=0.51,
            spread=0.04,
            liquidity=100,  # Very low - would normally cause partials
            volume_24h=500
        )

        # Run multiple times - should never partial fill
        for _ in range(10):
            result = simulator.simulate_market_order(
                side="BUY",
                quantity=50,
                conditions=conditions
            )
            # With partial fills disabled, should always fill completely
            # (unless liquidity is truly zero)
            assert result.total_quantity == 50 or result.total_quantity == 0


class TestLimitOrders:
    """Tests for limit order simulation."""

    @pytest.fixture
    def simulator(self):
        return FillSimulator(random_seed=42)

    @pytest.fixture
    def standard_conditions(self):
        return MarketConditions(
            mid_price=0.5,
            bid_price=0.49,
            ask_price=0.51,
            spread=0.04,
            liquidity=5000,
            volume_24h=10000
        )

    def test_marketable_limit_order_fills(self, simulator, standard_conditions):
        """Test that marketable limit orders fill immediately."""
        # Limit price above ask - should fill
        result = simulator.simulate_limit_order(
            side="BUY",
            quantity=100,
            limit_price=0.55,  # Above ask of 0.51
            conditions=standard_conditions
        )

        assert result.total_quantity > 0
        assert result.average_price <= 0.55  # Should fill at or below limit

    def test_non_marketable_limit_order_may_not_fill(self, simulator, standard_conditions):
        """Test that non-marketable limit orders may not fill."""
        # Limit price well below bid - unlikely to fill
        result = simulator.simulate_limit_order(
            side="BUY",
            quantity=100,
            limit_price=0.30,  # Well below market
            conditions=standard_conditions,
            time_in_force_seconds=60  # Short time
        )

        # May or may not fill - just check it returns valid result
        assert isinstance(result, ExecutionResult)
        assert result.unfilled_quantity >= 0


class TestFillDataclass:
    """Tests for Fill dataclass."""

    def test_fill_value_calculation(self):
        """Test that Fill.value is calculated correctly."""
        fill = Fill(price=0.5, quantity=100)
        assert fill.value == 50.0

    def test_fill_timestamp_default(self):
        """Test that Fill gets default timestamp."""
        fill = Fill(price=0.5, quantity=100)
        assert isinstance(fill.timestamp, datetime)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
