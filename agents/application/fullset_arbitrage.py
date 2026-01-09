"""
Full-Set Arbitrage Engine for Polymarket Paper Trading

Implements Dutch Book arbitrage for multi-outcome markets (3+ outcomes).
When the sum of all YES prices < $1.00, buy all outcomes to lock in guaranteed profit.

CRITICAL: Uses /events endpoint (not /markets) to find all markets belonging to an event.
"""

import json
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import httpx

from agents.polymarket.gamma import GammaMarketClient


@dataclass
class FullSetOpportunity:
    """Represents a multi-outcome arbitrage opportunity."""
    event_id: str
    event_title: str
    markets: List[Dict[str, Any]]     # All markets in the event
    outcomes: List[str]               # All outcome names (one per market)
    outcome_prices: List[float]       # YES price for each market
    total_cost: float                 # Sum of all YES prices
    edge: float                       # 1.0 - total_cost
    edge_pct: float                   # Edge as percentage
    token_ids: List[str]              # YES token ID from each market
    num_outcomes: int                 # Number of outcomes (3+)
    liquidity: float                  # Minimum liquidity across all markets

    def to_dict(self) -> dict:
        return {
            'event_id': self.event_id,
            'event_title': self.event_title,
            'outcomes': self.outcomes,
            'outcome_prices': self.outcome_prices,
            'total_cost': self.total_cost,
            'edge': self.edge,
            'edge_pct': self.edge_pct,
            'token_ids': self.token_ids,
            'num_outcomes': self.num_outcomes,
            'liquidity': self.liquidity
        }


class FullSetArbitrageEngine:
    """
    Scans multi-outcome events (3+ outcomes) where sum of all YES prices < $1.00.
    Implements Dutch Book arbitrage by buying all outcomes.

    Uses /events endpoint to find all markets belonging to a single event.
    """

    MIN_EDGE = 0.005       # 0.5% minimum edge
    MIN_OUTCOMES = 3       # At least 3 outcomes (exclude binary markets)
    MIN_LIQUIDITY = 500    # Minimum liquidity per outcome

    def __init__(self):
        self.gamma = GammaMarketClient()

    def get_multi_outcome_events(self, limit: int = 200) -> List[Dict]:
        """
        Fetch events with 3+ outcome markets.
        Uses /events endpoint which includes nested markets.
        """
        events_with_markets = []

        # Fetch active events
        params = {
            "active": "true",
            "closed": "false",
            "limit": limit
        }

        try:
            response = httpx.get(self.gamma.gamma_events_endpoint, params=params)
            if response.status_code != 200:
                print(f"Failed to fetch events: HTTP {response.status_code}")
                return events_with_markets

            events = response.json()

            for event in events:
                markets = event.get('markets', [])
                # Filter to events with 3+ markets (multi-outcome)
                if len(markets) >= self.MIN_OUTCOMES:
                    events_with_markets.append(event)

        except Exception as e:
            print(f"Error fetching events: {e}")

        return events_with_markets

    def _parse_outcome_prices(self, market: Dict) -> List[float]:
        """Parse outcome prices from market data."""
        prices = market.get('outcomePrices')
        if not prices:
            return []

        if isinstance(prices, str):
            try:
                prices = json.loads(prices)
            except json.JSONDecodeError:
                return []

        result = []
        for p in prices:
            try:
                result.append(float(p))
            except (TypeError, ValueError):
                continue
        return result

    def _parse_token_ids(self, market: Dict) -> List[str]:
        """Parse CLOB token IDs from market data."""
        token_ids = market.get('clobTokenIds')
        if not token_ids:
            return []

        if isinstance(token_ids, str):
            try:
                token_ids = json.loads(token_ids)
            except json.JSONDecodeError:
                return []

        return [str(t) for t in token_ids]

    def _analyze_event(self, event: Dict) -> Optional[FullSetOpportunity]:
        """
        Analyze a multi-outcome event for Dutch Book opportunity.

        Logic:
        1. Get all markets under the event
        2. For each market, extract the YES price (outcomePrices[0])
        3. Sum all YES prices
        4. If sum < 1.0, we have arbitrage
        """
        try:
            markets = event.get('markets', [])
            if len(markets) < self.MIN_OUTCOMES:
                return None

            outcomes = []
            outcome_prices = []
            token_ids = []
            liquidities = []
            valid_markets = []

            for market in markets:
                # Skip inactive or closed markets
                if market.get('active') is False or market.get('closed') is True:
                    continue

                # Get the YES price (first outcome price)
                prices = self._parse_outcome_prices(market)
                if not prices or prices[0] <= 0 or prices[0] >= 1.0:
                    continue

                # Get token ID for YES outcome
                market_token_ids = self._parse_token_ids(market)
                if not market_token_ids:
                    continue

                # Get market liquidity
                liquidity = float(market.get('liquidity', 0) or 0)
                if liquidity < self.MIN_LIQUIDITY:
                    continue

                # Extract outcome name from market question
                question = market.get('question', '')
                # For multi-outcome events, the question often IS the outcome
                # e.g., "Donald Trump" in "Who wins 2028 election?"
                outcome_name = market.get('groupItemTitle') or question

                outcomes.append(outcome_name)
                outcome_prices.append(prices[0])  # YES price
                token_ids.append(market_token_ids[0])  # YES token ID
                liquidities.append(liquidity)
                valid_markets.append(market)

            # Need at least MIN_OUTCOMES valid markets
            if len(valid_markets) < self.MIN_OUTCOMES:
                return None

            total_cost = sum(outcome_prices)
            edge = 1.0 - total_cost

            # Only return if there's positive edge
            if edge <= 0:
                return None

            return FullSetOpportunity(
                event_id=str(event.get('id', '')),
                event_title=event.get('title', ''),
                markets=valid_markets,
                outcomes=outcomes,
                outcome_prices=outcome_prices,
                total_cost=total_cost,
                edge=edge,
                edge_pct=(edge / total_cost) * 100 if total_cost > 0 else 0,
                token_ids=token_ids,
                num_outcomes=len(valid_markets),
                liquidity=min(liquidities) if liquidities else 0
            )

        except Exception as e:
            print(f"Error analyzing event: {e}")
            return None

    def scan_all_events(self, limit: int = 200) -> List[FullSetOpportunity]:
        """Scan all active events for full-set arbitrage opportunities."""
        opportunities = []

        # Fetch multi-outcome events
        events = self.get_multi_outcome_events(limit=limit)

        for event in events:
            opp = self._analyze_event(event)
            if opp and opp.edge >= self.MIN_EDGE:
                opportunities.append(opp)

        # Sort by edge (highest first)
        return sorted(opportunities, key=lambda x: -x.edge)

    def calculate_fullset_trade(
        self,
        opportunity: FullSetOpportunity,
        budget: float
    ) -> Dict[str, Any]:
        """
        Calculate exact quantities for a full-set arbitrage trade.

        For full-set arbitrage, we buy equal pairs of all outcomes.
        """
        total_cost = opportunity.total_cost

        # Calculate how many complete sets we can buy
        num_sets = budget / total_cost

        # Calculate cost and quantity for each outcome
        quantities = []
        costs = []

        for price in opportunity.outcome_prices:
            qty = num_sets  # Same quantity for each outcome
            cost = qty * price
            quantities.append(qty)
            costs.append(cost)

        total_spent = sum(costs)

        # Guaranteed payout: one outcome wins, paying $1 per share
        # We have num_sets shares of the winning outcome
        guaranteed_payout = num_sets
        guaranteed_profit = guaranteed_payout - total_spent

        return {
            'budget': budget,
            'num_sets': num_sets,
            'quantities': quantities,
            'costs': costs,
            'total_cost': total_spent,
            'guaranteed_payout': guaranteed_payout,
            'guaranteed_profit': guaranteed_profit,
            'profit_pct': (guaranteed_profit / total_spent) * 100 if total_spent > 0 else 0
        }

    def find_best_opportunities(
        self,
        min_edge_pct: float = 0.5,
        min_liquidity: float = 500,
        min_outcomes: int = 3,
        limit: int = 10
    ) -> List[FullSetOpportunity]:
        """Find the best full-set arbitrage opportunities matching criteria."""

        # Temporarily adjust minimum outcomes if requested
        original_min = self.MIN_OUTCOMES
        self.MIN_OUTCOMES = min_outcomes

        all_opportunities = self.scan_all_events()

        # Restore original setting
        self.MIN_OUTCOMES = original_min

        # Filter by criteria
        filtered = [
            opp for opp in all_opportunities
            if opp.edge_pct >= min_edge_pct
            and opp.liquidity >= min_liquidity
            and opp.num_outcomes >= min_outcomes
        ]

        return filtered[:limit]


def print_fullset_opportunities(opportunities: List[FullSetOpportunity]):
    """Pretty print full-set arbitrage opportunities."""
    if not opportunities:
        print("No full-set arbitrage opportunities found.")
        return

    print("\n" + "="*70)
    print("  FULL-SET ARBITRAGE OPPORTUNITIES (Dutch Book)")
    print("  Buy ALL outcomes when sum of YES prices < $1.00")
    print("="*70)

    for i, opp in enumerate(opportunities[:10], 1):
        print(f"\n{i}. {opp.event_title[:60]}{'...' if len(opp.event_title) > 60 else ''}")
        print(f"   Outcomes: {opp.num_outcomes}")
        print(f"   Total Cost: ${opp.total_cost:.4f}")
        print(f"   Edge: ${opp.edge:.4f} ({opp.edge_pct:.2f}%)")
        print(f"   Min Liquidity: ${opp.liquidity:,.0f}")
        print("   Prices:")
        for outcome, price in zip(opp.outcomes[:5], opp.outcome_prices[:5]):
            outcome_short = outcome[:30] + "..." if len(outcome) > 30 else outcome
            print(f"      {outcome_short}: ${price:.4f}")
        if len(opp.outcomes) > 5:
            print(f"      ... and {len(opp.outcomes) - 5} more outcomes")

    print("\n" + "="*70)


if __name__ == "__main__":
    engine = FullSetArbitrageEngine()
    print("Scanning for full-set arbitrage opportunities...")
    opportunities = engine.find_best_opportunities(
        min_edge_pct=0.1,
        min_liquidity=100,
        min_outcomes=3
    )
    print_fullset_opportunities(opportunities)
