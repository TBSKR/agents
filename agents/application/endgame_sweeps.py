"""
Endgame Sweeps Engine for Polymarket Paper Trading

Find markets where one outcome is 95-99% certain (price = $0.95-$0.99).
Buy these positions and wait for resolution to get $1.00.

Uses API tags as primary filter (most reliable), keyword matching as fallback.
Filters out volatile/sports markets to reduce risk of reversals.
"""

import json
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import httpx

from agents.polymarket.gamma import GammaMarketClient


# Sports keywords to exclude (volatile, reversible outcomes)
SPORTS_KEYWORDS = [
    "game", "match", "score", "nba", "nfl", "mlb", "nhl",
    "premier league", "world cup", "champion", "playoff",
    "finals", "series", "vs.", "versus", "win", "lose",
    "basketball", "football", "soccer", "baseball", "hockey",
    "tennis", "golf", "ufc", "boxing", "mma"
]

# Political/economic keywords (preferred - more deterministic)
POLITICAL_KEYWORDS = [
    "president", "election", "congress", "senate", "vote",
    "nominee", "cabinet", "secretary", "governor", "mayor",
    "primary", "caucus", "delegate", "electoral"
]

# Tags that indicate sports (from API)
EXCLUDE_TAG_LABELS = ["sports", "esports", "gaming", "nba", "nfl", "mlb"]

# Tags that indicate preferred markets
PREFERRED_TAG_LABELS = ["politics", "elections", "government", "economy", "crypto"]


@dataclass
class EndgameOpportunity:
    """Represents a near-certain outcome to sweep."""
    market_id: str
    question: str
    outcome: str              # "Yes" or "No"
    price: float              # Current price (0.95-0.99)
    expected_payout: float    # $1.00 on resolution
    edge: float               # 1.0 - price
    edge_pct: float           # Edge as percentage
    token_id: str
    end_date: str
    market_type: str          # "political", "crypto", "sports", "other"
    tags: List[str]           # Raw tags from API
    volume: float
    liquidity: float
    # New fields for enhanced filtering
    spread: float = 0.0                       # Bid-ask spread
    days_until_resolution: Optional[float] = None
    time_penalty: float = 0.0                 # Edge penalty for long duration
    adjusted_edge: float = 0.0                # edge * (1 - time_penalty)
    annualized_return: float = 0.0            # Annualized ROI

    def to_dict(self) -> dict:
        return {
            'market_id': self.market_id,
            'question': self.question,
            'outcome': self.outcome,
            'price': self.price,
            'expected_payout': self.expected_payout,
            'edge': self.edge,
            'edge_pct': self.edge_pct,
            'token_id': self.token_id,
            'end_date': self.end_date,
            'market_type': self.market_type,
            'tags': self.tags,
            'volume': self.volume,
            'liquidity': self.liquidity,
            'spread': self.spread,
            'days_until_resolution': self.days_until_resolution,
            'adjusted_edge': self.adjusted_edge,
            'annualized_return': self.annualized_return
        }


class EndgameSweepEngine:
    """
    Find markets where one outcome is 95-99% certain.
    Buy and hold until resolution for guaranteed profit.

    Uses layered filtering:
    1. API tags (most reliable)
    2. Keyword matching (fallback)
    """

    MIN_PRICE = 0.95
    MAX_PRICE = 0.99
    MIN_LIQUIDITY = 500
    MIN_LIQUIDITY_PER_OUTCOME = 200  # $200 minimum
    MAX_SPREAD = 0.10                # 10% max spread

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
        """Calculate edge penalty based on time to resolution."""
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
            return 0.75

    def _classify_market_type(self, event: Dict, market: Dict) -> str:
        """
        Classify market based on API tags and keywords.

        Layer 1: Check event['tags'] field (most reliable)
        Layer 2: Keyword matching on question/title (fallback)
        """
        # Layer 1: API Tags (most reliable)
        tags = event.get('tags', [])
        if isinstance(tags, list):
            tag_labels = []
            for t in tags:
                if isinstance(t, dict):
                    label = t.get('label', '').lower()
                    tag_labels.append(label)
                elif isinstance(t, str):
                    tag_labels.append(t.lower())

            # Check for sports (exclude)
            if any(excl in label for label in tag_labels for excl in EXCLUDE_TAG_LABELS):
                return "sports"

            # Check for preferred types
            if any(pref in label for label in tag_labels for pref in ['politic', 'election', 'government']):
                return "political"
            if any(pref in label for label in tag_labels for pref in ['crypto', 'bitcoin', 'ethereum']):
                return "crypto"
            if any('econ' in label for label in tag_labels):
                return "economic"

        # Layer 2: Keyword fallback
        question = market.get('question', '').lower()
        title = event.get('title', '').lower()
        description = market.get('description', '').lower()
        combined_text = f"{question} {title} {description}"

        # Check for sports keywords (exclude)
        if any(kw in combined_text for kw in SPORTS_KEYWORDS):
            return "sports"

        # Check for political keywords (preferred)
        if any(kw in combined_text for kw in POLITICAL_KEYWORDS):
            return "political"

        # Check for crypto
        if any(kw in combined_text for kw in ['bitcoin', 'btc', 'ethereum', 'eth', 'crypto', 'blockchain']):
            return "crypto"

        return "other"

    def _extract_tag_labels(self, event: Dict) -> List[str]:
        """Extract tag labels from event."""
        tags = event.get('tags', [])
        labels = []
        if isinstance(tags, list):
            for t in tags:
                if isinstance(t, dict):
                    label = t.get('label', '')
                    if label:
                        labels.append(label)
                elif isinstance(t, str):
                    labels.append(t)
        return labels

    def _is_near_certain(self, price: float) -> bool:
        """Check if price indicates near certainty."""
        return self.MIN_PRICE <= price <= self.MAX_PRICE

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

    def _fetch_events_with_markets(self, limit: int = 200) -> List[Dict]:
        """Fetch active events with their markets."""
        try:
            params = {
                "active": "true",
                "closed": "false",
                "limit": limit
            }
            response = httpx.get(self.gamma.gamma_events_endpoint, params=params)
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            print(f"Error fetching events: {e}")
        return []

    def scan_endgame_opportunities(
        self,
        min_price: float = 0.95,
        max_price: float = 0.99,
        exclude_sports: bool = True,
        min_liquidity: float = 500,
        max_days: int = 365,
        limit: int = 20,
        sort_by: str = "annualized"  # "edge" or "annualized"
    ) -> List[EndgameOpportunity]:
        """
        Scan for endgame sweep opportunities.

        Finds markets where YES or NO price is 95-99% (near certain).
        Filters out sports if requested.

        Enhanced filtering:
        - Uses liquidityClob if available
        - Checks spread
        - Checks if accepting orders
        - Applies time penalty for long-duration markets
        """
        opportunities = []

        # Fetch events with markets
        events = self._fetch_events_with_markets(limit=200)

        for event in events:
            markets = event.get('markets', [])

            for market in markets:
                # Skip inactive or closed markets
                if market.get('active') is False or market.get('closed') is True:
                    continue

                # Skip if not accepting orders
                if market.get('acceptingOrders') is False:
                    continue

                # Get prices
                prices = self._parse_outcome_prices(market)
                if len(prices) < 2:
                    continue

                # Get token IDs
                token_ids = self._parse_token_ids(market)
                if len(token_ids) < 2:
                    continue

                # Check liquidity - prefer CLOB liquidity
                liquidity_clob = float(market.get('liquidityClob', 0) or 0)
                liquidity = liquidity_clob if liquidity_clob > 0 else float(market.get('liquidity', 0) or 0)
                if liquidity < min_liquidity:
                    continue

                # Check spread
                spread = float(market.get('spread', 0) or 0)
                if spread > self.MAX_SPREAD:
                    continue

                # Get end date and calculate time-related fields
                end_date = market.get('endDate', '')
                days_until = self._calculate_days_until_resolution(end_date)

                # Filter by max days
                if days_until is not None and days_until > max_days:
                    continue

                time_penalty = self._calculate_time_penalty(days_until)

                # Classify market type
                market_type = self._classify_market_type(event, market)

                # Filter out sports if requested
                if exclude_sports and market_type == "sports":
                    continue

                # Check both YES and NO prices for near-certainty
                outcomes = market.get('outcomes', ['Yes', 'No'])
                if isinstance(outcomes, str):
                    try:
                        outcomes = json.loads(outcomes)
                    except json.JSONDecodeError:
                        outcomes = ['Yes', 'No']

                for i, price in enumerate(prices[:2]):  # Only check YES (0) and NO (1)
                    if min_price <= price <= max_price:
                        edge = 1.0 - price
                        edge_pct = (edge / price) * 100 if price > 0 else 0
                        adjusted_edge = edge * (1 - time_penalty)

                        # Calculate annualized return
                        if days_until and days_until > 0:
                            annualized_return = (adjusted_edge / price) * (365 / days_until) * 100
                        else:
                            annualized_return = edge_pct

                        opp = EndgameOpportunity(
                            market_id=str(market.get('id', '')),
                            question=market.get('question', ''),
                            outcome=outcomes[i] if i < len(outcomes) else ('Yes' if i == 0 else 'No'),
                            price=price,
                            expected_payout=1.0,
                            edge=edge,
                            edge_pct=edge_pct,
                            token_id=token_ids[i] if i < len(token_ids) else '',
                            end_date=end_date,
                            market_type=market_type,
                            tags=self._extract_tag_labels(event),
                            volume=float(market.get('volume', 0) or 0),
                            liquidity=liquidity,
                            spread=spread,
                            days_until_resolution=days_until,
                            time_penalty=time_penalty,
                            adjusted_edge=adjusted_edge,
                            annualized_return=annualized_return
                        )
                        opportunities.append(opp)

        # Sort by chosen metric
        if sort_by == "annualized":
            opportunities = sorted(opportunities, key=lambda x: -x.annualized_return)
        else:
            opportunities = sorted(opportunities, key=lambda x: -x.edge)

        return opportunities[:limit]

    def calculate_sweep_trade(
        self,
        opportunity: EndgameOpportunity,
        budget: float
    ) -> Dict[str, Any]:
        """
        Calculate trade for endgame sweep.

        Simple: buy as much as possible at current price.
        Expected payout is $1.00 per share at resolution.
        """
        quantity = budget / opportunity.price
        expected_payout = quantity * 1.0  # $1 per share
        guaranteed_profit = expected_payout - budget

        return {
            'budget': budget,
            'quantity': quantity,
            'cost': budget,
            'expected_payout': expected_payout,
            'guaranteed_profit': guaranteed_profit,
            'profit_pct': (guaranteed_profit / budget) * 100 if budget > 0 else 0,
            'price': opportunity.price,
            'outcome': opportunity.outcome
        }

    def find_best_opportunities(
        self,
        min_price: float = 0.95,
        max_price: float = 0.99,
        exclude_sports: bool = True,
        prefer_political: bool = True,
        min_liquidity: float = 500,
        max_days: int = 365,
        limit: int = 10,
        sort_by: str = "annualized"  # "edge" or "annualized"
    ) -> List[EndgameOpportunity]:
        """Find the best endgame sweep opportunities."""

        opportunities = self.scan_endgame_opportunities(
            min_price=min_price,
            max_price=max_price,
            exclude_sports=exclude_sports,
            min_liquidity=min_liquidity,
            limit=limit * 3  # Fetch more to filter
        )

        # Filter by max days until resolution
        filtered = []
        for opp in opportunities:
            if opp.days_until_resolution is not None and opp.days_until_resolution > max_days:
                continue
            filtered.append(opp)
        opportunities = filtered

        # Sort by chosen metric
        if sort_by == "annualized":
            opportunities = sorted(opportunities, key=lambda x: -x.annualized_return)
        elif prefer_political:
            # Sort to prioritize political markets, then by edge
            def sort_key(opp):
                type_priority = {
                    'political': 0,
                    'economic': 1,
                    'crypto': 2,
                    'other': 3,
                    'sports': 4  # Should be filtered but just in case
                }
                return (type_priority.get(opp.market_type, 3), -opp.edge)

            opportunities = sorted(opportunities, key=sort_key)
        else:
            opportunities = sorted(opportunities, key=lambda x: -x.edge)

        return opportunities[:limit]


def print_endgame_opportunities(opportunities: List[EndgameOpportunity], show_details: bool = False):
    """Pretty print endgame sweep opportunities."""
    if not opportunities:
        print("No endgame sweep opportunities found.")
        return

    print("\n" + "="*70)
    print("  ENDGAME SWEEP OPPORTUNITIES")
    print("  Near-certain outcomes (95-99%) to buy and hold until resolution")
    print("="*70)

    for i, opp in enumerate(opportunities[:10], 1):
        print(f"\n{i}. {opp.question[:55]}{'...' if len(opp.question) > 55 else ''}")
        print(f"   Outcome: {opp.outcome} @ ${opp.price:.4f}")
        print(f"   Edge: ${opp.edge:.4f} ({opp.edge_pct:.2f}%)")

        # Show time penalty and adjusted edge
        if opp.time_penalty > 0:
            print(f"   Adjusted Edge: ${opp.adjusted_edge:.4f} (-{opp.time_penalty*100:.0f}% time penalty)")

        # Show resolution time and annualized return
        if opp.days_until_resolution is not None:
            days = opp.days_until_resolution
            if days < 1:
                print(f"   Resolution: < 1 day | Annualized: {opp.annualized_return:.1f}%")
            else:
                print(f"   Resolution: {days:.0f} days | Annualized: {opp.annualized_return:.1f}%")

        # Show liquidity and spread
        print(f"   Liquidity: ${opp.liquidity:,.0f} | Spread: {opp.spread*100:.1f}%")

        if show_details:
            print(f"   Type: {opp.market_type.upper()}")
            if opp.tags:
                print(f"   Tags: {', '.join(opp.tags[:3])}")

    print("\n" + "="*70)


if __name__ == "__main__":
    engine = EndgameSweepEngine()
    print("Scanning for endgame sweep opportunities...")
    opportunities = engine.find_best_opportunities(
        min_price=0.95,
        max_price=0.99,
        exclude_sports=True,
        prefer_political=True,
        min_liquidity=100
    )
    print_endgame_opportunities(opportunities)
