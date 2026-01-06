"""
Gabagool Trading Strategy

Math-based trading that guarantees profit by buying both YES and NO
when their combined price is less than $1.00.

No AI predictions. No guessing. Pure math.

Strategy:
1. Find markets where YES + NO < $1.00
2. Buy the cheap side when it dips
3. Build balanced positions over time
4. Lock in profit when avg_YES + avg_NO < $1.00
"""

import json
import time
import httpx
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class MarketPosition:
    """Track cumulative position in a market."""
    market_id: str
    question: str
    qty_yes: float = 0.0
    qty_no: float = 0.0
    cost_yes: float = 0.0
    cost_no: float = 0.0
    trades: List[Dict] = field(default_factory=list)
    
    @property
    def avg_yes(self) -> float:
        return self.cost_yes / self.qty_yes if self.qty_yes > 0 else 0
    
    @property
    def avg_no(self) -> float:
        return self.cost_no / self.qty_no if self.qty_no > 0 else 0
    
    @property
    def pair_cost(self) -> float:
        """Combined average cost per pair."""
        return self.avg_yes + self.avg_no
    
    @property
    def is_profit_locked(self) -> bool:
        """True if guaranteed profit regardless of outcome."""
        if self.qty_yes == 0 or self.qty_no == 0:
            return False
        return self.pair_cost < 0.98
    
    @property
    def guaranteed_profit(self) -> float:
        """Calculate guaranteed profit at settlement."""
        if not self.is_profit_locked:
            return 0.0
        min_qty = min(self.qty_yes, self.qty_no)
        total_cost = self.cost_yes + self.cost_no
        return min_qty - total_cost
    
    @property
    def profit_pct(self) -> float:
        """Profit as percentage of investment."""
        total_cost = self.cost_yes + self.cost_no
        if total_cost == 0:
            return 0.0
        return (self.guaranteed_profit / total_cost) * 100
    
    def to_dict(self) -> Dict:
        return {
            'market_id': self.market_id,
            'question': self.question,
            'qty_yes': self.qty_yes,
            'qty_no': self.qty_no,
            'cost_yes': self.cost_yes,
            'cost_no': self.cost_no,
            'avg_yes': self.avg_yes,
            'avg_no': self.avg_no,
            'pair_cost': self.pair_cost,
            'is_profit_locked': self.is_profit_locked,
            'guaranteed_profit': self.guaranteed_profit,
            'profit_pct': self.profit_pct,
            'num_trades': len(self.trades)
        }


class GabagoolTrader:
    """
    Implements the Gabagool strategy: buy both sides cheap, lock in profit.
    
    No AI. No predictions. Just math.
    """
    
    GAMMA_URL = "https://gamma-api.polymarket.com"
    
    def __init__(self, data_dir: str = "paper_trading_data"):
        self.positions: Dict[str, MarketPosition] = {}
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True)
        self.positions_file = self.data_dir / "gabagool_positions.json"
        self._load_positions()
    
    def _load_positions(self):
        """Load saved positions."""
        if self.positions_file.exists():
            try:
                with open(self.positions_file) as f:
                    data = json.load(f)
                for market_id, pos_data in data.items():
                    self.positions[market_id] = MarketPosition(
                        market_id=pos_data['market_id'],
                        question=pos_data['question'],
                        qty_yes=pos_data['qty_yes'],
                        qty_no=pos_data['qty_no'],
                        cost_yes=pos_data['cost_yes'],
                        cost_no=pos_data['cost_no'],
                        trades=pos_data.get('trades', [])
                    )
            except Exception as e:
                print(f"Could not load positions: {e}")
    
    def _save_positions(self):
        """Save positions to disk."""
        data = {}
        for market_id, pos in self.positions.items():
            data[market_id] = {
                'market_id': pos.market_id,
                'question': pos.question,
                'qty_yes': pos.qty_yes,
                'qty_no': pos.qty_no,
                'cost_yes': pos.cost_yes,
                'cost_no': pos.cost_no,
                'trades': pos.trades
            }
        with open(self.positions_file, 'w') as f:
            json.dump(data, f, indent=2)
    
    def scan_opportunity(self, yes_price: float, no_price: float) -> Optional[Dict]:
        """
        Check if there's an arbitrage opportunity.
        
        Returns edge info if YES + NO < $1.00
        """
        if yes_price <= 0 or no_price <= 0:
            return None
        if yes_price >= 1 or no_price >= 1:
            return None
            
        total = yes_price + no_price
        
        if total < 0.995:  # At least 0.5% edge
            edge = 1.0 - total
            return {
                'edge': edge,
                'edge_pct': (edge / total) * 100,
                'yes_price': yes_price,
                'no_price': no_price,
                'total': total,
                'action': 'BUY_BOTH'
            }
        return None
    
    def find_cheap_side(self, yes_price: float, no_price: float, threshold: float = 0.45) -> Optional[str]:
        """
        Identify which side is currently cheap (good to buy).
        
        In volatile markets, one side often dips temporarily.
        """
        if yes_price < threshold:
            return 'YES'
        if no_price < threshold:
            return 'NO'
        
        # If neither is super cheap, buy the cheaper one if there's decent edge
        if yes_price + no_price < 0.98:
            return 'YES' if yes_price < no_price else 'NO'
        
        return None
    
    def simulate_buy(self, market_id: str, side: str, price: float, quantity: float) -> Dict:
        """
        Simulate buying and update position.
        
        Returns new position state.
        """
        if market_id not in self.positions:
            self.positions[market_id] = MarketPosition(
                market_id=market_id,
                question=f"Market {market_id}"
            )
        
        pos = self.positions[market_id]
        cost = price * quantity
        
        trade = {
            'side': side,
            'price': price,
            'quantity': quantity,
            'cost': cost,
            'timestamp': time.time()
        }
        
        if side == 'YES':
            pos.qty_yes += quantity
            pos.cost_yes += cost
        else:
            pos.qty_no += quantity
            pos.cost_no += cost
        
        pos.trades.append(trade)
        self._save_positions()
        
        return pos.to_dict()
    
    def get_btc_markets(self) -> List[Dict]:
        """
        Fetch BTC 15-minute UP/DOWN markets.
        
        These are the markets where gabagool makes money.
        """
        try:
            params = {
                "active": "true",
                "closed": "false",
                "limit": 50
            }
            response = httpx.get(f"{self.GAMMA_URL}/markets", params=params, timeout=10)
            
            if response.status_code != 200:
                return []
            
            markets = response.json()
            btc_markets = []
            
            for m in markets:
                question = m.get('question', '').lower()
                # Look for BTC price markets (15-min, hourly, etc.)
                if 'btc' in question or 'bitcoin' in question:
                    if 'price' in question or 'above' in question or 'below' in question:
                        btc_markets.append(self._parse_market(m))
            
            return btc_markets
            
        except Exception as e:
            print(f"Error fetching BTC markets: {e}")
            return []
    
    def get_all_markets_with_edge(self, min_edge_pct: float = 0.5) -> List[Dict]:
        """
        Scan all markets for arbitrage opportunities.
        """
        try:
            params = {"active": "true", "closed": "false", "limit": 100}
            response = httpx.get(f"{self.GAMMA_URL}/markets", params=params, timeout=10)
            
            if response.status_code != 200:
                return []
            
            opportunities = []
            for m in response.json():
                parsed = self._parse_market(m)
                if parsed:
                    opp = self.scan_opportunity(parsed['yes_price'], parsed['no_price'])
                    if opp and opp['edge_pct'] >= min_edge_pct:
                        parsed.update(opp)
                        opportunities.append(parsed)
            
            return sorted(opportunities, key=lambda x: -x['edge_pct'])
            
        except Exception as e:
            print(f"Error scanning markets: {e}")
            return []
    
    def _parse_market(self, market: Dict) -> Optional[Dict]:
        """Parse market data from API response."""
        try:
            outcome_prices = market.get('outcomePrices')
            if not outcome_prices:
                return None
            
            if isinstance(outcome_prices, str):
                outcome_prices = json.loads(outcome_prices)
            
            if len(outcome_prices) != 2:
                return None
            
            yes_price = float(outcome_prices[0])
            no_price = float(outcome_prices[1])
            
            if yes_price <= 0 or no_price <= 0:
                return None
            
            return {
                'market_id': str(market.get('id', '')),
                'question': market.get('question', ''),
                'yes_price': yes_price,
                'no_price': no_price,
                'total': yes_price + no_price,
                'volume': float(market.get('volume', 0) or 0),
                'liquidity': float(market.get('liquidity', 0) or 0)
            }
        except:
            return None
    
    def execute_gabagool_trade(self, market: Dict, budget: float) -> Dict:
        """
        Execute the gabagool strategy on a market.
        
        Buy both YES and NO to lock in profit.
        """
        yes_price = market['yes_price']
        no_price = market['no_price']
        market_id = market['market_id']
        
        # Calculate quantities for equal position
        total_cost_per_pair = yes_price + no_price
        num_pairs = budget / total_cost_per_pair
        
        # Buy both sides
        yes_result = self.simulate_buy(market_id, 'YES', yes_price, num_pairs)
        no_result = self.simulate_buy(market_id, 'NO', no_price, num_pairs)
        
        # Update question
        if market_id in self.positions:
            self.positions[market_id].question = market['question']
            self._save_positions()
        
        return {
            'market_id': market_id,
            'question': market['question'],
            'yes_bought': num_pairs,
            'no_bought': num_pairs,
            'total_cost': budget,
            'position': self.positions[market_id].to_dict()
        }
    
    def get_all_positions(self) -> List[Dict]:
        """Get all current positions."""
        return [pos.to_dict() for pos in self.positions.values()]
    
    def get_position(self, market_id: str) -> Optional[Dict]:
        """Get position for a specific market."""
        if market_id in self.positions:
            return self.positions[market_id].to_dict()
        return None
    
    def get_summary(self) -> Dict:
        """Get overall portfolio summary."""
        total_invested = 0
        total_guaranteed_profit = 0
        locked_positions = 0
        
        for pos in self.positions.values():
            total_invested += pos.cost_yes + pos.cost_no
            if pos.is_profit_locked:
                locked_positions += 1
                total_guaranteed_profit += pos.guaranteed_profit
        
        return {
            'total_positions': len(self.positions),
            'locked_positions': locked_positions,
            'total_invested': total_invested,
            'total_guaranteed_profit': total_guaranteed_profit,
            'overall_profit_pct': (total_guaranteed_profit / total_invested * 100) if total_invested > 0 else 0
        }


def print_positions(trader: GabagoolTrader):
    """Pretty print all positions."""
    positions = trader.get_all_positions()
    
    if not positions:
        print("\nNo positions yet.")
        return
    
    print("\n" + "="*70)
    print("  GABAGOOL POSITIONS")
    print("="*70)
    
    for pos in positions:
        status = "✅ LOCKED" if pos['is_profit_locked'] else "⏳ Building"
        print(f"\n📊 {pos['question'][:50]}...")
        print(f"   YES: {pos['qty_yes']:.2f} @ avg ${pos['avg_yes']:.4f} = ${pos['cost_yes']:.2f}")
        print(f"   NO:  {pos['qty_no']:.2f} @ avg ${pos['avg_no']:.4f} = ${pos['cost_no']:.2f}")
        print(f"   Pair Cost: ${pos['pair_cost']:.4f} | {status}")
        if pos['is_profit_locked']:
            print(f"   💰 Guaranteed Profit: ${pos['guaranteed_profit']:.2f} ({pos['profit_pct']:.2f}%)")
    
    summary = trader.get_summary()
    print("\n" + "-"*70)
    print(f"  Total Invested: ${summary['total_invested']:.2f}")
    print(f"  Locked Positions: {summary['locked_positions']}/{summary['total_positions']}")
    print(f"  Guaranteed Profit: ${summary['total_guaranteed_profit']:.2f}")
    print("="*70)


if __name__ == "__main__":
    trader = GabagoolTrader()
    
    print("Scanning for opportunities...")
    opportunities = trader.get_all_markets_with_edge(min_edge_pct=0.1)
    
    if opportunities:
        print(f"\nFound {len(opportunities)} opportunities:")
        for opp in opportunities[:5]:
            print(f"  - {opp['question'][:40]}... Edge: {opp['edge_pct']:.2f}%")
    else:
        print("No arbitrage opportunities found (market is efficient)")
    
    print_positions(trader)
