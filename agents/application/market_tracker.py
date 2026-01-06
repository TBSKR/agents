import json
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

from agents.polymarket.gamma import GammaMarketClient


@dataclass
class MarketSnapshot:
    market_id: str
    question: str
    outcomes: List[str]
    outcome_prices: List[float]
    volume: Optional[float]
    liquidity: Optional[float]
    spread: Optional[float]
    active: bool
    
    def get_price_for_outcome(self, outcome: str) -> Optional[float]:
        try:
            idx = self.outcomes.index(outcome)
            return self.outcome_prices[idx]
        except (ValueError, IndexError):
            return None

    def to_dict(self) -> dict:
        return {
            'market_id': self.market_id,
            'question': self.question,
            'outcomes': self.outcomes,
            'outcome_prices': self.outcome_prices,
            'volume': self.volume,
            'liquidity': self.liquidity,
            'spread': self.spread,
            'active': self.active
        }


class MarketTracker:
    def __init__(self):
        self.gamma = GammaMarketClient()
        self._cache: Dict[str, MarketSnapshot] = {}

    def get_market_snapshot(self, market_id: str) -> Optional[MarketSnapshot]:
        try:
            market_data = self.gamma.get_market(market_id)
            if not market_data:
                return None

            outcomes = market_data.get('outcomes', [])
            if isinstance(outcomes, str):
                outcomes = json.loads(outcomes)

            outcome_prices = market_data.get('outcomePrices', [])
            if isinstance(outcome_prices, str):
                outcome_prices = json.loads(outcome_prices)
            outcome_prices = [float(p) for p in outcome_prices]

            snapshot = MarketSnapshot(
                market_id=str(market_id),
                question=market_data.get('question', ''),
                outcomes=outcomes,
                outcome_prices=outcome_prices,
                volume=float(market_data.get('volume', 0) or 0),
                liquidity=float(market_data.get('liquidity', 0) or 0),
                spread=float(market_data.get('spread', 0) or 0),
                active=market_data.get('active', False)
            )
            
            self._cache[market_id] = snapshot
            return snapshot

        except Exception as e:
            print(f"Error fetching market {market_id}: {e}")
            return None

    def get_current_price(self, market_id: str, outcome: str) -> Optional[float]:
        snapshot = self.get_market_snapshot(market_id)
        if snapshot:
            return snapshot.get_price_for_outcome(outcome)
        return None

    def get_prices_for_positions(self, positions: List[Any]) -> Dict[str, float]:
        prices = {}
        for position in positions:
            market_id = position.market_id
            outcome = position.outcome
            
            price = self.get_current_price(market_id, outcome)
            if price is not None:
                prices[position.token_id] = price
        
        return prices

    def get_cached_snapshot(self, market_id: str) -> Optional[MarketSnapshot]:
        return self._cache.get(market_id)

    def clear_cache(self):
        self._cache.clear()

    def get_market_details_for_logging(self, market_id: str) -> Dict[str, Any]:
        snapshot = self.get_market_snapshot(market_id)
        if not snapshot:
            return {}
        
        return {
            'market_id': snapshot.market_id,
            'question': snapshot.question,
            'outcomes': json.dumps(snapshot.outcomes),
            'outcome_prices': json.dumps(snapshot.outcome_prices),
            'volume': snapshot.volume,
            'liquidity': snapshot.liquidity,
            'spread': snapshot.spread
        }
