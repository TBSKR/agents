"""
Trading Service - Wraps existing trading engines for API use
"""

import sys
from pathlib import Path
from typing import List, Dict, Any, Optional

# Add project root to path for imports
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from agents.application.paper_trader import PaperTrader
from agents.application.fullset_arbitrage import FullSetArbitrageEngine
from agents.application.endgame_sweeps import EndgameSweepEngine
from agents.application.oracle_timing import OracleTimingEngine
from agents.application.rewards_tracker import HoldingRewardsTracker


class TradingService:
    """
    Singleton service that wraps all trading engines.
    Provides a unified interface for the API layer.
    """

    _instance: Optional['TradingService'] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._initialized = True
        self.trader = PaperTrader(initial_balance=1000.0, use_realistic_fills=True)
        self.fullset_engine = FullSetArbitrageEngine()
        self.endgame_engine = EndgameSweepEngine()
        self.oracle_engine = OracleTimingEngine()

    @property
    def rewards_tracker(self) -> HoldingRewardsTracker:
        """Lazy-load rewards tracker with current portfolio."""
        return HoldingRewardsTracker(self.trader.portfolio)

    def get_portfolio_summary(self) -> Dict[str, Any]:
        """Get current portfolio summary."""
        return self.trader.portfolio.get_portfolio_summary()

    def get_positions(self) -> List[Dict[str, Any]]:
        """Get all open positions."""
        positions = self.trader.portfolio.get_open_positions()
        return [p.to_dict() for p in positions]

    def get_status(self) -> Dict[str, Any]:
        """Get full status including portfolio and positions."""
        return self.trader.get_status()

    def update_position_prices(self) -> Dict[str, Any]:
        """Update all position prices from market."""
        return self.trader.update_positions()

    def scan_fullset_opportunities(
        self,
        min_edge_pct: float = 0.5,
        min_liquidity: float = 500,
        min_outcomes: int = 3,
        max_days: int = 365,
        limit: int = 10,
        sort_by: str = "annualized"
    ) -> List[Dict[str, Any]]:
        """Scan for full-set arbitrage opportunities."""
        opportunities = self.fullset_engine.find_best_opportunities(
            min_edge_pct=min_edge_pct,
            min_liquidity=min_liquidity,
            min_outcomes=min_outcomes,
            max_days=max_days,
            limit=limit,
            sort_by=sort_by
        )
        return [self._format_fullset_opportunity(o) for o in opportunities]

    def scan_endgame_opportunities(
        self,
        min_price: float = 0.95,
        max_price: float = 0.99,
        min_liquidity: float = 500,
        max_days: int = 365,
        limit: int = 10,
        sort_by: str = "annualized"
    ) -> List[Dict[str, Any]]:
        """Scan for endgame sweep opportunities."""
        opportunities = self.endgame_engine.find_best_opportunities(
            min_price=min_price,
            max_price=max_price,
            min_liquidity=min_liquidity,
            max_days=max_days,
            limit=limit,
            sort_by=sort_by
        )
        return [self._format_endgame_opportunity(o) for o in opportunities]

    def scan_oracle_opportunities(
        self,
        min_edge_pct: float = 1.0,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Scan for oracle timing opportunities."""
        opportunities = self.oracle_engine.scan_oracle_opportunities(
            min_edge_pct=min_edge_pct,
            limit=limit
        )
        return [self._format_oracle_opportunity(o) for o in opportunities]

    def get_rewards_summary(self) -> Dict[str, Any]:
        """Get holding rewards summary."""
        summary = self.rewards_tracker.get_rewards_summary()
        return summary.to_dict()

    def execute_trade_cycle(self) -> Dict[str, Any]:
        """Execute a single AI-driven trade cycle."""
        return self.trader.execute_paper_trade_cycle()

    def close_position(self, token_id: str) -> Dict[str, Any]:
        """Close a specific position."""
        return self.trader.close_position(token_id)

    def _format_fullset_opportunity(self, opp) -> Dict[str, Any]:
        """Format a FullSetOpportunity for API response."""
        return {
            "id": opp.event_id,
            "name": opp.event_title,
            "strategy": "fullset",
            "edge": opp.edge,
            "edge_pct": opp.edge_pct,
            "annualized_return": opp.annualized_return,
            "liquidity": opp.liquidity,
            "days_until_resolution": opp.days_until_resolution,
            "total_cost": opp.total_cost,
            "num_outcomes": opp.num_outcomes,
            "adjusted_edge": opp.adjusted_edge,
            "time_penalty": opp.time_penalty,
            "avg_spread": opp.avg_spread,
        }

    def _format_endgame_opportunity(self, opp) -> Dict[str, Any]:
        """Format an EndgameOpportunity for API response."""
        return {
            "id": opp.market_id,
            "name": opp.question,
            "strategy": "endgame",
            "outcome": opp.outcome,
            "price": opp.price,
            "edge": opp.edge,
            "edge_pct": opp.edge_pct,
            "annualized_return": opp.annualized_return,
            "liquidity": opp.liquidity,
            "days_until_resolution": opp.days_until_resolution,
            "market_type": opp.market_type,
            "adjusted_edge": opp.adjusted_edge,
            "time_penalty": opp.time_penalty,
        }

    def _format_oracle_opportunity(self, opp) -> Dict[str, Any]:
        """Format an OracleOpportunity for API response."""
        return {
            "id": opp.market_id,
            "name": opp.question,
            "strategy": "oracle",
            "asset": opp.asset,
            "threshold_price": opp.threshold_price,
            "threshold_direction": opp.threshold_direction,
            "current_price": opp.current_price,
            "polymarket_price": opp.polymarket_price,
            "edge": opp.edge,
            "edge_pct": opp.edge_pct,
            "event_occurred": opp.event_occurred,
            "resolution_window": opp.resolution_window,
        }


# Global service instance
trading_service = TradingService()
