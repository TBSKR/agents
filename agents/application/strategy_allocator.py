"""
Strategy Allocator for Multi-Strategy Paper Trading

Implements priority-based capital allocation across multiple strategies:
- Oracle timing: Highest priority (time-sensitive)
- Full-set arbitrage: High priority (guaranteed profit)
- Endgame sweeps: Medium priority (high confidence)
- Holding rewards: Lowest priority (passive income)
"""

from dataclasses import dataclass
from typing import Dict, Optional
from enum import Enum


class StrategyType(Enum):
    """Available trading strategies in priority order."""
    ORACLE = "oracle"      # Highest priority - time-sensitive
    FULLSET = "fullset"    # High priority - guaranteed arbitrage
    ENDGAME = "endgame"    # Medium priority - high confidence
    REWARDS = "rewards"    # Lowest priority - passive income


@dataclass
class StrategyBudget:
    """Configuration for a strategy's budget allocation."""
    allocation_pct: float   # Max % of portfolio for this strategy
    max_per_trade: float    # Max $ per individual trade
    min_edge: float         # Minimum edge required to execute


class StrategyAllocator:
    """
    Manages capital allocation across multiple trading strategies.

    Features:
    - Priority-based allocation (Oracle > FullSet > Endgame > Rewards)
    - Per-strategy limits to prevent over-concentration
    - Edge-based filtering to ensure minimum profitability
    - Dynamic budget adjustment based on deployed capital
    """

    # Default allocation settings per strategy
    DEFAULT_ALLOCATIONS = {
        StrategyType.ORACLE: StrategyBudget(
            allocation_pct=0.40,   # 40% max for oracle timing
            max_per_trade=500,    # $500 max per trade
            min_edge=0.02         # 2% minimum edge
        ),
        StrategyType.FULLSET: StrategyBudget(
            allocation_pct=0.30,   # 30% max for full-set arb
            max_per_trade=300,    # $300 max per trade
            min_edge=0.005        # 0.5% minimum edge
        ),
        StrategyType.ENDGAME: StrategyBudget(
            allocation_pct=0.20,   # 20% max for endgame sweeps
            max_per_trade=200,    # $200 max per trade
            min_edge=0.01         # 1% minimum edge
        ),
        StrategyType.REWARDS: StrategyBudget(
            allocation_pct=0.10,   # 10% max for rewards
            max_per_trade=1000,   # $1000 max per position
            min_edge=0.0          # No minimum (passive)
        ),
    }

    def __init__(
        self,
        total_capital: float,
        allocations: Optional[Dict[StrategyType, StrategyBudget]] = None
    ):
        """
        Initialize the allocator with total capital and optional custom allocations.

        Args:
            total_capital: Total portfolio value available for allocation
            allocations: Optional custom allocation settings per strategy
        """
        self.total_capital = total_capital
        self.allocations = allocations or self.DEFAULT_ALLOCATIONS.copy()
        self.deployed: Dict[StrategyType, float] = {s: 0.0 for s in StrategyType}

    def update_capital(self, new_total: float):
        """Update total capital (e.g., after profits/losses)."""
        self.total_capital = new_total

    def get_strategy_limit(self, strategy: StrategyType) -> float:
        """Get maximum capital that can be deployed to a strategy."""
        alloc = self.allocations.get(strategy)
        if not alloc:
            return 0
        return self.total_capital * alloc.allocation_pct

    def get_available_budget(self, strategy: StrategyType) -> float:
        """Get remaining budget available for a strategy."""
        limit = self.get_strategy_limit(strategy)
        deployed = self.deployed.get(strategy, 0)
        return max(0, limit - deployed)

    def get_trade_budget(
        self,
        strategy: StrategyType,
        edge_pct: float = 0,
        requested_amount: Optional[float] = None
    ) -> float:
        """
        Get budget for a specific trade.

        Args:
            strategy: The strategy type
            edge_pct: Edge percentage of the opportunity (as decimal, e.g., 0.02 for 2%)
            requested_amount: Optional specific amount requested

        Returns:
            Budget to use for this trade (may be 0 if constraints not met)
        """
        alloc = self.allocations.get(strategy)
        if not alloc:
            return 0

        # Check minimum edge requirement
        if edge_pct < alloc.min_edge:
            return 0

        # Get available budget for this strategy
        available = self.get_available_budget(strategy)
        if available <= 0:
            return 0

        # Apply per-trade maximum
        max_trade = min(available, alloc.max_per_trade)

        # If specific amount requested, use minimum of request and max
        if requested_amount is not None:
            return min(requested_amount, max_trade)

        return max_trade

    def record_trade(self, strategy: StrategyType, amount: float):
        """Record a trade execution, updating deployed capital."""
        self.deployed[strategy] = self.deployed.get(strategy, 0) + amount

    def release_capital(self, strategy: StrategyType, amount: float):
        """Release capital back when a position is closed."""
        current = self.deployed.get(strategy, 0)
        self.deployed[strategy] = max(0, current - amount)

    def get_allocation_summary(self) -> Dict[str, Dict[str, float]]:
        """Get summary of current allocations."""
        summary = {}
        for strategy in StrategyType:
            limit = self.get_strategy_limit(strategy)
            deployed = self.deployed.get(strategy, 0)
            available = self.get_available_budget(strategy)
            summary[strategy.value] = {
                'limit': limit,
                'deployed': deployed,
                'available': available,
                'utilization_pct': (deployed / limit * 100) if limit > 0 else 0
            }
        return summary

    def get_priority_order(self) -> list:
        """Get strategies in priority order (highest first)."""
        return [
            StrategyType.ORACLE,
            StrategyType.FULLSET,
            StrategyType.ENDGAME,
            StrategyType.REWARDS
        ]

    def suggest_allocation(
        self,
        opportunities: Dict[StrategyType, list]
    ) -> Dict[StrategyType, list]:
        """
        Suggest which opportunities to take based on priority and budget.

        Args:
            opportunities: Dict mapping strategy type to list of opportunities

        Returns:
            Dict mapping strategy type to list of opportunities to execute
        """
        suggestions = {}

        for strategy in self.get_priority_order():
            strat_opps = opportunities.get(strategy, [])
            if not strat_opps:
                continue

            available = self.get_available_budget(strategy)
            alloc = self.allocations.get(strategy)
            if not alloc or available <= 0:
                continue

            selected = []
            remaining_budget = available

            for opp in strat_opps:
                # Assume opportunity has an 'edge' or 'edge_pct' attribute
                edge = getattr(opp, 'edge_pct', 0) / 100  # Convert to decimal
                if edge < alloc.min_edge:
                    continue

                trade_size = min(alloc.max_per_trade, remaining_budget)
                if trade_size <= 0:
                    break

                selected.append(opp)
                remaining_budget -= trade_size

            if selected:
                suggestions[strategy] = selected

        return suggestions


def print_allocation_summary(allocator: StrategyAllocator):
    """Pretty print the allocation summary."""
    summary = allocator.get_allocation_summary()

    print("\n" + "="*60)
    print("  STRATEGY ALLOCATION SUMMARY")
    print("="*60)
    print(f"  Total Capital: ${allocator.total_capital:,.2f}")
    print("-"*60)

    for strategy in StrategyType:
        info = summary[strategy.value]
        print(f"\n  {strategy.value.upper()}")
        print(f"    Limit:       ${info['limit']:,.2f}")
        print(f"    Deployed:    ${info['deployed']:,.2f}")
        print(f"    Available:   ${info['available']:,.2f}")
        print(f"    Utilization: {info['utilization_pct']:.1f}%")

    print("\n" + "="*60)


if __name__ == "__main__":
    # Example usage
    allocator = StrategyAllocator(total_capital=10000)

    print_allocation_summary(allocator)

    # Simulate some trades
    print("\nSimulating trades...")

    budget = allocator.get_trade_budget(StrategyType.ORACLE, edge_pct=0.05)
    print(f"Oracle trade budget (5% edge): ${budget:.2f}")
    allocator.record_trade(StrategyType.ORACLE, budget)

    budget = allocator.get_trade_budget(StrategyType.FULLSET, edge_pct=0.01)
    print(f"Fullset trade budget (1% edge): ${budget:.2f}")
    allocator.record_trade(StrategyType.FULLSET, budget)

    budget = allocator.get_trade_budget(StrategyType.ENDGAME, edge_pct=0.02)
    print(f"Endgame trade budget (2% edge): ${budget:.2f}")
    allocator.record_trade(StrategyType.ENDGAME, budget)

    print_allocation_summary(allocator)
