"""
Arbitrage Engine for Polymarket Paper Trading

Implements professional trading strategies:
1. Sum-to-One Arbitrage: Buy YES + NO when total < $1.00
2. Hedged Positions: Balance exposure for guaranteed profit
3. Opportunity Scanner: Find best risk-free trades
"""

import json
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import httpx

from agents.polymarket.gamma import GammaMarketClient


@dataclass
class ArbitrageOpportunity:
    """Represents an arbitrage opportunity."""
    market_id: str
    question: str
    yes_price: float
    no_price: float
    total_cost: float
    edge: float
    edge_pct: float
    volume: float
    liquidity: float
    outcomes: List[str]
    token_ids: List[str]
    
    def to_dict(self) -> dict:
        return {
            'market_id': self.market_id,
            'question': self.question,
            'yes_price': self.yes_price,
            'no_price': self.no_price,
            'total_cost': self.total_cost,
            'edge': self.edge,
            'edge_pct': self.edge_pct,
            'volume': self.volume,
            'liquidity': self.liquidity
        }


class ArbitrageEngine:
    """Finds and calculates arbitrage opportunities on Polymarket."""
    
    MIN_EDGE = 0.005  # 0.5% minimum edge
    MIN_LIQUIDITY = 1000  # Minimum $1000 liquidity
    
    def __init__(self):
        self.gamma = GammaMarketClient()
    
    def scan_all_markets(self, limit: int = 200) -> List[ArbitrageOpportunity]:
        """Scan all active markets for arbitrage opportunities."""
        opportunities = []
        
        # Fetch active markets
        params = {"active": "true", "closed": "false", "limit": limit}
        response = httpx.get(self.gamma.gamma_markets_endpoint, params=params)
        
        if response.status_code != 200:
            return opportunities
        
        markets = response.json()
        
        for market in markets:
            opp = self._analyze_market(market)
            if opp and opp.edge >= self.MIN_EDGE:
                opportunities.append(opp)
        
        # Sort by edge (highest first)
        return sorted(opportunities, key=lambda x: -x.edge)
    
    def _analyze_market(self, market: dict) -> Optional[ArbitrageOpportunity]:
        """Analyze a single market for arbitrage opportunity."""
        try:
            # Parse outcome prices
            outcome_prices = market.get('outcomePrices')
            if not outcome_prices:
                return None
            
            if isinstance(outcome_prices, str):
                outcome_prices = json.loads(outcome_prices)
            
            # Only handle binary markets (YES/NO)
            if len(outcome_prices) != 2:
                return None
            
            yes_price = float(outcome_prices[0])
            no_price = float(outcome_prices[1])
            
            # Skip invalid prices
            if yes_price <= 0 or no_price <= 0:
                return None
            if yes_price >= 1 or no_price >= 1:
                return None
            
            total_cost = yes_price + no_price
            edge = 1.0 - total_cost
            
            # Only return if there's positive edge
            if edge <= 0:
                return None
            
            # Parse other fields
            outcomes = market.get('outcomes', ['Yes', 'No'])
            if isinstance(outcomes, str):
                outcomes = json.loads(outcomes)
            
            token_ids = market.get('clobTokenIds', [])
            if isinstance(token_ids, str):
                token_ids = json.loads(token_ids)
            
            liquidity = float(market.get('liquidity', 0) or 0)
            volume = float(market.get('volume', 0) or 0)
            
            return ArbitrageOpportunity(
                market_id=str(market.get('id', '')),
                question=market.get('question', ''),
                yes_price=yes_price,
                no_price=no_price,
                total_cost=total_cost,
                edge=edge,
                edge_pct=(edge / total_cost) * 100 if total_cost > 0 else 0,
                volume=volume,
                liquidity=liquidity,
                outcomes=outcomes,
                token_ids=token_ids if token_ids else []
            )
            
        except Exception as e:
            return None
    
    def calculate_arbitrage_trade(
        self, 
        opportunity: ArbitrageOpportunity, 
        budget: float
    ) -> Dict[str, Any]:
        """Calculate exact quantities for an arbitrage trade."""
        
        total_cost = opportunity.total_cost
        
        # Calculate how many pairs we can buy
        num_pairs = budget / total_cost
        
        yes_cost = num_pairs * opportunity.yes_price
        no_cost = num_pairs * opportunity.no_price
        total_spent = yes_cost + no_cost
        
        # Guaranteed payout is num_pairs (since one side always wins)
        guaranteed_payout = num_pairs
        guaranteed_profit = guaranteed_payout - total_spent
        
        return {
            'budget': budget,
            'num_pairs': num_pairs,
            'yes_quantity': num_pairs,
            'no_quantity': num_pairs,
            'yes_cost': yes_cost,
            'no_cost': no_cost,
            'total_cost': total_spent,
            'guaranteed_payout': guaranteed_payout,
            'guaranteed_profit': guaranteed_profit,
            'profit_pct': (guaranteed_profit / total_spent) * 100 if total_spent > 0 else 0
        }
    
    def find_best_opportunities(
        self, 
        min_edge_pct: float = 0.5,
        min_liquidity: float = 1000,
        limit: int = 10
    ) -> List[ArbitrageOpportunity]:
        """Find the best arbitrage opportunities matching criteria."""
        
        all_opportunities = self.scan_all_markets()
        
        # Filter by criteria
        filtered = [
            opp for opp in all_opportunities
            if opp.edge_pct >= min_edge_pct 
            and opp.liquidity >= min_liquidity
        ]
        
        return filtered[:limit]
    
    def get_market_prices(self, market_id: str) -> Optional[Dict[str, float]]:
        """Get current YES/NO prices for a specific market."""
        try:
            market = self.gamma.get_market(market_id)
            if not market:
                return None
            
            outcome_prices = market.get('outcomePrices')
            if isinstance(outcome_prices, str):
                outcome_prices = json.loads(outcome_prices)
            
            if len(outcome_prices) >= 2:
                return {
                    'yes': float(outcome_prices[0]),
                    'no': float(outcome_prices[1]),
                    'total': float(outcome_prices[0]) + float(outcome_prices[1])
                }
        except:
            pass
        return None


def print_opportunities(opportunities: List[ArbitrageOpportunity]):
    """Pretty print arbitrage opportunities."""
    if not opportunities:
        print("No arbitrage opportunities found.")
        return
    
    print("\n" + "="*70)
    print("  ARBITRAGE OPPORTUNITIES (Sum-to-One < $1.00)")
    print("="*70)
    
    for i, opp in enumerate(opportunities[:10], 1):
        print(f"\n{i}. {opp.question[:50]}{'...' if len(opp.question) > 50 else ''}")
        print(f"   YES: ${opp.yes_price:.4f}  |  NO: ${opp.no_price:.4f}  |  Total: ${opp.total_cost:.4f}")
        print(f"   Edge: ${opp.edge:.4f} ({opp.edge_pct:.2f}%)  |  Liquidity: ${opp.liquidity:,.0f}")
    
    print("\n" + "="*70)


if __name__ == "__main__":
    engine = ArbitrageEngine()
    print("Scanning markets for arbitrage opportunities...")
    opportunities = engine.find_best_opportunities(min_edge_pct=0.1, min_liquidity=100)
    print_opportunities(opportunities)
