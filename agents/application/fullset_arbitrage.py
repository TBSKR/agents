"""
Full-Set Arbitrage Engine for Polymarket Paper Trading

Implements Dutch Book arbitrage for multi-outcome markets (3+ outcomes).
When the sum of all YES prices < $1.00, buy all outcomes to lock in guaranteed profit.

CRITICAL: Uses /events endpoint (not /markets) to find all markets belonging to an event.
"""

import json
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple
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
    # New fields for enhanced filtering
    liquidity_per_outcome: List[float] = None  # Per-outcome breakdown
    avg_spread: float = 0.0           # Average spread across outcomes
    end_date: str = ""                # Resolution date
    days_until_resolution: Optional[float] = None
    time_penalty: float = 0.0         # Edge penalty for long duration
    adjusted_edge: float = 0.0        # edge * (1 - time_penalty)
    annualized_return: float = 0.0    # Annualized ROI

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
            'liquidity': self.liquidity,
            'avg_spread': self.avg_spread,
            'days_until_resolution': self.days_until_resolution,
            'adjusted_edge': self.adjusted_edge,
            'annualized_return': self.annualized_return
        }


class FullSetArbitrageEngine:
    """
    Scans multi-outcome events (3+ outcomes) where sum of all YES prices < $1.00.
    Implements Dutch Book arbitrage by buying all outcomes.

    Uses /events endpoint to find all markets belonging to a single event.
    """

    MIN_EDGE = 0.005       # 0.5% minimum edge
    MIN_OUTCOMES = 3       # At least 3 outcomes (exclude binary markets)
    MIN_LIQUIDITY = 500    # Minimum total market liquidity
    MIN_LIQUIDITY_PER_OUTCOME = 200  # $200 minimum per outcome
    MAX_SPREAD = 0.10      # 10% max spread allowed

    # Resolution time penalties
    SHORT_TERM_DAYS = 7       # No penalty
    MEDIUM_TERM_DAYS = 30     # 10% edge penalty
    LONG_TERM_DAYS = 90       # 25% edge penalty
    VERY_LONG_TERM_DAYS = 180 # 50% edge penalty

    def __init__(self):
        self.gamma = GammaMarketClient()

    def _parse_end_date(self, end_date_str: str) -> Optional[datetime]:
        """Parse end date string to datetime."""
        if not end_date_str:
            return None

        formats = [
            "%Y-%m-%dT%H:%M:%S.%fZ",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%d"
        ]

        for fmt in formats:
            try:
                return datetime.strptime(end_date_str, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        return None

    def _calculate_days_until_resolution(self, end_date_str: str) -> Optional[float]:
        """Calculate days until market resolution."""
        end_dt = self._parse_end_date(end_date_str)
        if not end_dt:
            return None

        now = datetime.now(timezone.utc)
        delta = end_dt - now
        return max(0, delta.total_seconds() / 86400)

    def _calculate_time_penalty(self, days: Optional[float]) -> float:
        """
        Calculate edge penalty based on time to resolution.
        Longer duration = higher penalty (opportunity cost).
        """
        if days is None:
            return 0.25  # Unknown = 25% penalty

        if days <= self.SHORT_TERM_DAYS:
            return 0.0
        elif days <= self.MEDIUM_TERM_DAYS:
            return 0.10
        elif days <= self.LONG_TERM_DAYS:
            return 0.25
        elif days <= self.VERY_LONG_TERM_DAYS:
            return 0.50
        else:
            return 0.75  # 75% penalty for >180 days

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

        Enhanced filtering:
        - Uses liquidityClob if available (better for order book depth)
        - Checks spread (skip if > 10%)
        - Checks if market is accepting orders
        - Applies time penalty for long-duration markets
        """
        try:
            markets = event.get('markets', [])
            if len(markets) < self.MIN_OUTCOMES:
                return None

            outcomes = []
            outcome_prices = []
            token_ids = []
            liquidities = []
            spreads = []
            valid_markets = []

            for market in markets:
                # Skip inactive or closed markets
                if market.get('active') is False or market.get('closed') is True:
                    continue

                # Skip if not accepting orders
                if market.get('acceptingOrders') is False:
                    continue

                # Get the YES price (first outcome price)
                prices = self._parse_outcome_prices(market)
                if not prices or prices[0] <= 0 or prices[0] >= 1.0:
                    continue

                # Get token ID for YES outcome
                market_token_ids = self._parse_token_ids(market)
                if not market_token_ids:
                    continue

                # Get market liquidity - prefer CLOB liquidity if available
                liquidity_clob = float(market.get('liquidityClob', 0) or 0)
                liquidity = liquidity_clob if liquidity_clob > 0 else float(market.get('liquidity', 0) or 0)

                # Skip if insufficient liquidity per outcome
                if liquidity < self.MIN_LIQUIDITY_PER_OUTCOME:
                    continue

                # Check spread - skip if too wide
                spread = float(market.get('spread', 0) or 0)
                if spread > self.MAX_SPREAD:
                    continue

                # Extract outcome name from market question
                question = market.get('question', '')
                outcome_name = market.get('groupItemTitle') or question

                outcomes.append(outcome_name)
                outcome_prices.append(prices[0])  # YES price
                token_ids.append(market_token_ids[0])  # YES token ID
                liquidities.append(liquidity)
                spreads.append(spread)
                valid_markets.append(market)

            # Need at least MIN_OUTCOMES valid markets
            if len(valid_markets) < self.MIN_OUTCOMES:
                return None

            total_cost = sum(outcome_prices)
            edge = 1.0 - total_cost

            # Only return if there's positive edge
            if edge <= 0:
                return None

            # Calculate edge percentage
            edge_pct = (edge / total_cost) * 100 if total_cost > 0 else 0

            # Calculate average spread
            avg_spread = sum(spreads) / len(spreads) if spreads else 0

            # Get end date and calculate time-related fields
            end_date = event.get('endDate', '')
            days_until = self._calculate_days_until_resolution(end_date)
            time_penalty = self._calculate_time_penalty(days_until)
            adjusted_edge = edge * (1 - time_penalty)

            # Calculate annualized return
            if days_until and days_until > 0:
                annualized_return = (adjusted_edge / total_cost) * (365 / days_until) * 100
            else:
                annualized_return = edge_pct  # If resolution is immediate

            return FullSetOpportunity(
                event_id=str(event.get('id', '')),
                event_title=event.get('title', ''),
                markets=valid_markets,
                outcomes=outcomes,
                outcome_prices=outcome_prices,
                total_cost=total_cost,
                edge=edge,
                edge_pct=edge_pct,
                token_ids=token_ids,
                num_outcomes=len(valid_markets),
                liquidity=min(liquidities) if liquidities else 0,
                liquidity_per_outcome=liquidities,
                avg_spread=avg_spread,
                end_date=end_date,
                days_until_resolution=days_until,
                time_penalty=time_penalty,
                adjusted_edge=adjusted_edge,
                annualized_return=annualized_return
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
        max_days: int = 365,
        limit: int = 10,
        sort_by: str = "annualized"  # "edge" or "annualized"
    ) -> List[FullSetOpportunity]:
        """Find the best full-set arbitrage opportunities matching criteria."""

        # Temporarily adjust minimum outcomes if requested
        original_min = self.MIN_OUTCOMES
        self.MIN_OUTCOMES = min_outcomes

        all_opportunities = self.scan_all_events()

        # Restore original setting
        self.MIN_OUTCOMES = original_min

        # Filter by criteria
        filtered = []
        for opp in all_opportunities:
            if opp.edge_pct < min_edge_pct:
                continue
            if opp.liquidity < min_liquidity:
                continue
            if opp.num_outcomes < min_outcomes:
                continue
            # Filter by max days until resolution
            if opp.days_until_resolution is not None and opp.days_until_resolution > max_days:
                continue
            filtered.append(opp)

        # Sort by chosen metric
        if sort_by == "annualized":
            filtered.sort(key=lambda x: -x.annualized_return)
        else:
            filtered.sort(key=lambda x: -x.edge)

        return filtered[:limit]


def print_fullset_opportunities(opportunities: List[FullSetOpportunity], show_details: bool = False):
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

        # Show time penalty and adjusted edge
        if opp.time_penalty > 0:
            print(f"   Adjusted Edge: ${opp.adjusted_edge:.4f} (-{opp.time_penalty*100:.0f}% time penalty)")

        # Show resolution time
        if opp.days_until_resolution is not None:
            days = opp.days_until_resolution
            if days < 1:
                print(f"   Resolution: < 1 day | Annualized: {opp.annualized_return:.1f}%")
            elif days < 30:
                print(f"   Resolution: {days:.0f} days | Annualized: {opp.annualized_return:.1f}%")
            else:
                print(f"   Resolution: {days:.0f} days | Annualized: {opp.annualized_return:.1f}%")

        # Show liquidity info
        print(f"   Min Liquidity: ${opp.liquidity:,.0f} | Avg Spread: {opp.avg_spread*100:.1f}%")

        if show_details:
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
