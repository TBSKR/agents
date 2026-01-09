"""
Oracle Timing Engine for Polymarket Paper Trading

Monitor external price feeds (Binance) and trade when event has occurred
but Polymarket oracle hasn't resolved yet.

Strategy:
1. Find crypto price threshold markets (BTC/ETH above/below X)
2. Monitor real-time external prices (Binance)
3. When external event has occurred but oracle hasn't resolved:
   - Buy YES if price crossed threshold in favorable direction
   - The market should resolve to $1.00
"""

import re
import json
import time
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
import httpx

from agents.polymarket.gamma import GammaMarketClient
from agents.connectors.binance_client import BinanceClient, PriceAlert


# Asset detection patterns
ASSET_PATTERNS = {
    'BTC': [r'\bbtc\b', r'\bbitcoin\b'],
    'ETH': [r'\beth\b', r'\bethereum\b'],
    'SOL': [r'\bsol\b', r'\bsolana\b'],
    'DOGE': [r'\bdoge\b', r'\bdogecoin\b'],
    'XRP': [r'\bxrp\b'],
}

# Direction patterns (order matters - check multi-word first)
DIRECTION_PATTERNS = [
    (r'(above|over|exceed|greater than|higher than|>\s*)', 'above'),
    (r'(below|under|less than|lower than|<\s*)', 'below'),
    (r'(reach|hit|touch|break)', 'above'),  # "reach $100k" implies above
]

# Price patterns (handle various formats)
PRICE_PATTERNS = [
    r'\$\s*([\d,]+(?:\.\d+)?)\s*m\b',              # $1m, $1.5m (millions)
    r'\$\s*([\d,]+(?:\.\d+)?)\s*k\b',              # $100k, $100.5k
    r'\$\s*([\d,]+(?:\.\d+)?)\s*(?:usd|dollars)?', # $100,000 USD
    r'([\d,]+(?:\.\d+)?)\s*(?:usd|dollars)',       # 100000 USD
    r'\$\s*([\d,]+(?:\.\d+)?)',                    # $100000
]

# Suffix multipliers
SUFFIX_MULTIPLIERS = {
    'm': 1_000_000,
    'k': 1_000,
}


@dataclass
class OracleOpportunity:
    """Represents an oracle timing exploit opportunity."""
    market_id: str
    question: str
    threshold_price: float      # e.g., 100000 for "BTC above $100k"
    threshold_direction: str    # "above" or "below"
    asset: str                  # "BTC", "ETH", etc.
    current_price: float        # Current external price
    event_occurred: bool        # Has the external event happened?
    polymarket_price: float     # Current Polymarket YES price
    expected_payout: float      # $1.00 if event occurred
    edge: float                 # 1.0 - polymarket_price
    edge_pct: float             # Edge as percentage
    token_id: str
    end_date: str
    resolution_window: str      # "15m", "1h", "daily"

    def to_dict(self) -> dict:
        return {
            'market_id': self.market_id,
            'question': self.question,
            'threshold_price': self.threshold_price,
            'threshold_direction': self.threshold_direction,
            'asset': self.asset,
            'current_price': self.current_price,
            'event_occurred': self.event_occurred,
            'polymarket_price': self.polymarket_price,
            'expected_payout': self.expected_payout,
            'edge': self.edge,
            'edge_pct': self.edge_pct,
            'token_id': self.token_id,
            'end_date': self.end_date,
            'resolution_window': self.resolution_window
        }


class OracleTimingEngine:
    """
    Monitor external price feeds and exploit oracle resolution delays.

    Strategy:
    1. Find crypto price threshold markets (BTC/ETH above/below X)
    2. Monitor real-time external prices (Binance)
    3. When external event has occurred but oracle hasn't resolved:
       - Buy YES if price crossed threshold in favorable direction
       - The market should resolve to $1.00
    """

    # Minimum edge to consider (as percentage)
    MIN_EDGE_PCT = 1.0

    # Keywords that indicate crypto price markets
    CRYPTO_KEYWORDS = ['btc', 'bitcoin', 'eth', 'ethereum', 'sol', 'solana', 'crypto']

    def __init__(self):
        self.gamma = GammaMarketClient()
        self.binance = BinanceClient()

    def _parse_threshold_from_question(
        self,
        question: str
    ) -> Optional[Tuple[str, str, float]]:
        """
        Extract (asset, direction, threshold_price) from market question.

        Handles various question formats:
        - "Will BTC be above $100,000 at 6pm?"
        - "BTC price > $100k"
        - "Bitcoin to exceed 100,000 USD"
        - "Will Ethereum be below 3.5k?"
        - "ETH under $3,500 by midnight?"
        - "Will Bitcoin reach $150k?"

        Returns: ("BTC", "above", 100000.0) or None if not parseable
        """
        question_lower = question.lower()

        # Find asset
        asset = None
        for symbol, patterns in ASSET_PATTERNS.items():
            if any(re.search(p, question_lower) for p in patterns):
                asset = symbol
                break

        if not asset:
            return None

        # Find direction
        direction = None
        for pattern, dir_value in DIRECTION_PATTERNS:
            if re.search(pattern, question_lower):
                direction = dir_value
                break

        if not direction:
            return None

        # Find price
        price = None
        matched_suffix = None

        # Try standard patterns first (patterns include suffix like 'm' or 'k')
        for i, pattern in enumerate(PRICE_PATTERNS):
            match = re.search(pattern, question_lower)
            if match:
                price_str = match.group(1).replace(',', '')
                price = float(price_str)
                # Check which pattern matched to determine suffix
                if i == 0:  # $1m pattern
                    matched_suffix = 'm'
                elif i == 1:  # $100k pattern
                    matched_suffix = 'k'
                break

        # Apply suffix multiplier if matched
        if price is not None and matched_suffix:
            price *= SUFFIX_MULTIPLIERS.get(matched_suffix, 1)

        # Handle shorthand like "100k" or "1m" without $ if no price found yet
        if price is None:
            match = re.search(r'\b([\d.]+)\s*([mk])\b', question_lower)
            if match:
                price = float(match.group(1))
                suffix = match.group(2)
                price *= SUFFIX_MULTIPLIERS.get(suffix, 1)

        if price is None:
            return None

        return (asset, direction, price)

    def _parse_resolution_window(self, question: str, end_date: str) -> str:
        """Detect resolution window from question or end date."""
        question_lower = question.lower()

        if any(x in question_lower for x in ['15 min', '15min', '15-min', 'every 15']):
            return "15m"
        if any(x in question_lower for x in ['hour', 'hourly', '1h', '60 min']):
            return "1h"
        if any(x in question_lower for x in ['daily', 'day', 'eod', 'end of day']):
            return "daily"
        if any(x in question_lower for x in ['week', 'weekly']):
            return "weekly"

        return "unknown"

    def _fetch_crypto_markets(self, limit: int = 200) -> List[Dict]:
        """Fetch markets that appear to be crypto price threshold markets."""
        crypto_markets = []

        try:
            params = {
                "active": "true",
                "closed": "false",
                "limit": limit
            }
            response = httpx.get(self.gamma.gamma_markets_endpoint, params=params)
            if response.status_code != 200:
                return crypto_markets

            markets = response.json()

            for market in markets:
                question = market.get('question', '').lower()

                # Check if it's a crypto price market
                if any(kw in question for kw in self.CRYPTO_KEYWORDS):
                    # Check if it has price threshold language
                    if any(re.search(p[0], question) for p in DIRECTION_PATTERNS):
                        crypto_markets.append(market)

        except Exception as e:
            print(f"Error fetching markets: {e}")

        return crypto_markets

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

        return [float(p) for p in prices if p]

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

    def scan_oracle_opportunities(
        self,
        min_edge_pct: float = 1.0,
        limit: int = 10
    ) -> List[OracleOpportunity]:
        """
        Scan for oracle timing exploit opportunities.

        Looks for:
        1. Price threshold markets (BTC/ETH)
        2. Where external price has crossed threshold
        3. But Polymarket price hasn't reached 0.95+ yet
        """
        opportunities = []

        # Get crypto price markets
        markets = self._fetch_crypto_markets(limit=200)

        for market in markets:
            question = market.get('question', '')
            threshold_info = self._parse_threshold_from_question(question)

            if not threshold_info:
                continue

            asset, direction, threshold = threshold_info

            # Check if threshold has been crossed
            alert = self.binance.check_threshold(asset, threshold, direction)

            if alert.crossed:
                # Event has occurred - check if Polymarket is lagging
                prices = self._parse_outcome_prices(market)
                if not prices:
                    continue

                yes_price = prices[0]

                # If YES price is still low, there's opportunity
                if yes_price < 0.95:
                    edge = 1.0 - yes_price
                    edge_pct = (edge / yes_price) * 100 if yes_price > 0 else 0

                    if edge_pct >= min_edge_pct:
                        token_ids = self._parse_token_ids(market)

                        opp = OracleOpportunity(
                            market_id=str(market.get('id', '')),
                            question=question,
                            threshold_price=threshold,
                            threshold_direction=direction,
                            asset=asset,
                            current_price=alert.current_price,
                            event_occurred=True,
                            polymarket_price=yes_price,
                            expected_payout=1.0,
                            edge=edge,
                            edge_pct=edge_pct,
                            token_id=token_ids[0] if token_ids else '',
                            end_date=market.get('endDate', ''),
                            resolution_window=self._parse_resolution_window(
                                question, market.get('endDate', '')
                            )
                        )
                        opportunities.append(opp)

        # Sort by edge (highest first)
        opportunities = sorted(opportunities, key=lambda x: -x.edge)

        return opportunities[:limit]

    def calculate_oracle_trade(
        self,
        opportunity: OracleOpportunity,
        budget: float
    ) -> Dict[str, Any]:
        """
        Calculate trade for oracle timing opportunity.

        When event has occurred, buy YES at current price.
        Expected payout is $1.00 per share at resolution.
        """
        quantity = budget / opportunity.polymarket_price
        expected_payout = quantity * 1.0
        guaranteed_profit = expected_payout - budget

        return {
            'budget': budget,
            'quantity': quantity,
            'cost': budget,
            'expected_payout': expected_payout,
            'guaranteed_profit': guaranteed_profit,
            'profit_pct': (guaranteed_profit / budget) * 100 if budget > 0 else 0,
            'price': opportunity.polymarket_price,
            'asset': opportunity.asset,
            'threshold': opportunity.threshold_price,
            'direction': opportunity.threshold_direction
        }

    def monitor_and_alert(
        self,
        poll_interval: float = 5.0,
        duration: float = 3600,
        callback=None
    ) -> List[OracleOpportunity]:
        """
        Continuously monitor for oracle timing opportunities.

        Args:
            poll_interval: Seconds between checks
            duration: Total monitoring duration in seconds
            callback: Optional function to call when opportunity found

        Returns:
            List of all opportunities found during monitoring
        """
        all_opportunities = []
        start_time = time.time()

        print(f"\nMonitoring for oracle timing opportunities...")
        print(f"Poll interval: {poll_interval}s | Duration: {duration}s")
        print("Press Ctrl+C to stop early\n")

        try:
            while time.time() - start_time < duration:
                opportunities = self.scan_oracle_opportunities(min_edge_pct=1.0)

                for opp in opportunities:
                    # Check if we've already seen this opportunity
                    seen = any(
                        o.market_id == opp.market_id
                        for o in all_opportunities
                    )

                    if not seen:
                        all_opportunities.append(opp)
                        print(f"\n{'='*60}")
                        print(f"NEW OPPORTUNITY DETECTED!")
                        print(f"{'='*60}")
                        print(f"Market: {opp.question[:50]}...")
                        print(f"Asset: {opp.asset}")
                        print(f"Threshold: {opp.threshold_direction} ${opp.threshold_price:,.0f}")
                        print(f"Current {opp.asset}: ${opp.current_price:,.2f}")
                        print(f"Polymarket YES: ${opp.polymarket_price:.4f}")
                        print(f"Edge: {opp.edge_pct:.2f}%")
                        print(f"EVENT OCCURRED - BUY NOW!")
                        print(f"{'='*60}\n")

                        if callback:
                            callback(opp)

                elapsed = time.time() - start_time
                remaining = duration - elapsed
                if remaining > 0:
                    print(f"\rMonitoring... {remaining:.0f}s remaining | Found: {len(all_opportunities)}", end='', flush=True)

                time.sleep(poll_interval)

        except KeyboardInterrupt:
            print("\n\nMonitoring stopped by user.")

        return all_opportunities


def print_oracle_opportunities(opportunities: List[OracleOpportunity]):
    """Pretty print oracle timing opportunities."""
    if not opportunities:
        print("No oracle timing opportunities found.")
        return

    print("\n" + "="*70)
    print("  ORACLE TIMING OPPORTUNITIES")
    print("  Threshold crossed but Polymarket hasn't fully priced in yet")
    print("="*70)

    for i, opp in enumerate(opportunities[:10], 1):
        print(f"\n{i}. {opp.question[:55]}{'...' if len(opp.question) > 55 else ''}")
        print(f"   Asset: {opp.asset}")
        print(f"   Threshold: {opp.threshold_direction} ${opp.threshold_price:,.0f}")
        print(f"   Current {opp.asset}: ${opp.current_price:,.2f}")
        print(f"   Polymarket YES: ${opp.polymarket_price:.4f}")
        print(f"   Edge: ${opp.edge:.4f} ({opp.edge_pct:.2f}%)")

        if opp.event_occurred:
            print(f"   STATUS: EVENT OCCURRED - TRADE SIGNAL!")
        else:
            print(f"   STATUS: Monitoring...")

        print(f"   Resolution: {opp.resolution_window}")

    print("\n" + "="*70)


if __name__ == "__main__":
    engine = OracleTimingEngine()

    # Test price parsing
    print("\n" + "="*50)
    print("  TESTING QUESTION PARSER")
    print("="*50)

    test_questions = [
        "Will BTC be above $100,000 at 6pm?",
        "BTC price > $100k",
        "Bitcoin to exceed 100,000 USD",
        "Will Ethereum be below 3.5k?",
        "ETH under $3,500 by midnight?",
        "Will Bitcoin reach $150k?",
        "Will SOL be above $200 on Friday?",
    ]

    for q in test_questions:
        result = engine._parse_threshold_from_question(q)
        if result:
            asset, direction, price = result
            print(f"\n  Q: {q}")
            print(f"  -> {asset} {direction} ${price:,.0f}")
        else:
            print(f"\n  Q: {q}")
            print(f"  -> Could not parse")

    print("\n" + "="*50)
    print("  SCANNING FOR OPPORTUNITIES")
    print("="*50)

    opportunities = engine.scan_oracle_opportunities(min_edge_pct=0.5)
    print_oracle_opportunities(opportunities)
