"""
Lightweight Market Watcher

Polls Polymarket API for price changes and opportunities.
Designed to run efficiently on MacBook Air M2.

Features:
- Gentle polling (5 second intervals by default)
- Spike detection (identify sudden price drops)
- Opportunity alerts
- Minimal CPU/memory usage
"""

import time
import json
import httpx
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass
from collections import deque


@dataclass
class PricePoint:
    """Single price observation."""
    timestamp: float
    yes_price: float
    no_price: float
    
    @property
    def total(self) -> float:
        return self.yes_price + self.no_price


class MarketWatcher:
    """
    Lightweight market price monitor.
    
    Watches for:
    1. Arbitrage opportunities (YES + NO < $1.00)
    2. Price spikes (sudden drops = buying opportunity)
    3. Trend changes
    """
    
    GAMMA_URL = "https://gamma-api.polymarket.com"
    
    def __init__(self, poll_interval: float = 5.0, history_size: int = 20):
        self.poll_interval = poll_interval  # Seconds between polls
        self.history_size = history_size    # Price points to keep
        self.price_history: Dict[str, deque] = {}
        self.callbacks: List[Callable] = []
        self.running = False
    
    def add_callback(self, callback: Callable):
        """Add callback for opportunity alerts."""
        self.callbacks.append(callback)
    
    def fetch_market_prices(self, market_id: str) -> Optional[PricePoint]:
        """Fetch current prices for a market."""
        try:
            response = httpx.get(
                f"{self.GAMMA_URL}/markets/{market_id}",
                timeout=5
            )
            if response.status_code != 200:
                return None
            
            data = response.json()
            outcome_prices = data.get('outcomePrices')
            
            if isinstance(outcome_prices, str):
                outcome_prices = json.loads(outcome_prices)
            
            if len(outcome_prices) >= 2:
                return PricePoint(
                    timestamp=time.time(),
                    yes_price=float(outcome_prices[0]),
                    no_price=float(outcome_prices[1])
                )
        except Exception as e:
            pass
        return None
    
    def fetch_all_markets(self, limit: int = 50) -> List[Dict]:
        """Fetch all active markets."""
        try:
            params = {"active": "true", "closed": "false", "limit": limit}
            response = httpx.get(f"{self.GAMMA_URL}/markets", params=params, timeout=10)
            
            if response.status_code != 200:
                return []
            
            markets = []
            for m in response.json():
                parsed = self._parse_market(m)
                if parsed:
                    markets.append(parsed)
            
            return markets
        except:
            return []
    
    def _parse_market(self, market: Dict) -> Optional[Dict]:
        """Parse market from API response."""
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
    
    def update_price(self, market_id: str, price_point: PricePoint):
        """Record a new price observation."""
        if market_id not in self.price_history:
            self.price_history[market_id] = deque(maxlen=self.history_size)
        
        self.price_history[market_id].append(price_point)
    
    def detect_spike(self, market_id: str, threshold: float = 0.10) -> Optional[Dict]:
        """
        Detect sudden price drops (buying opportunities).
        
        Returns spike info if price dropped > threshold in recent history.
        """
        if market_id not in self.price_history:
            return None
        
        history = self.price_history[market_id]
        if len(history) < 2:
            return None
        
        current = history[-1]
        previous = history[-2]
        
        # Check YES price drop
        if previous.yes_price > 0:
            yes_change = (current.yes_price - previous.yes_price) / previous.yes_price
            if yes_change < -threshold:
                return {
                    'type': 'YES_DROP',
                    'market_id': market_id,
                    'change_pct': yes_change * 100,
                    'old_price': previous.yes_price,
                    'new_price': current.yes_price,
                    'action': 'BUY_YES'
                }
        
        # Check NO price drop
        if previous.no_price > 0:
            no_change = (current.no_price - previous.no_price) / previous.no_price
            if no_change < -threshold:
                return {
                    'type': 'NO_DROP',
                    'market_id': market_id,
                    'change_pct': no_change * 100,
                    'old_price': previous.no_price,
                    'new_price': current.no_price,
                    'action': 'BUY_NO'
                }
        
        return None
    
    def check_arbitrage(self, market_id: str) -> Optional[Dict]:
        """Check if market has arbitrage opportunity."""
        if market_id not in self.price_history:
            return None
        
        history = self.price_history[market_id]
        if not history:
            return None
        
        current = history[-1]
        total = current.total
        
        if total < 0.99:
            return {
                'type': 'ARBITRAGE',
                'market_id': market_id,
                'yes_price': current.yes_price,
                'no_price': current.no_price,
                'total': total,
                'edge': 1.0 - total,
                'edge_pct': ((1.0 - total) / total) * 100,
                'action': 'BUY_BOTH'
            }
        
        return None
    
    def scan_once(self) -> List[Dict]:
        """
        Scan all markets once for opportunities.
        
        Returns list of opportunities found.
        """
        opportunities = []
        markets = self.fetch_all_markets()
        
        for market in markets:
            market_id = market['market_id']
            
            # Update price history
            price_point = PricePoint(
                timestamp=time.time(),
                yes_price=market['yes_price'],
                no_price=market['no_price']
            )
            self.update_price(market_id, price_point)
            
            # Check for spike
            spike = self.detect_spike(market_id)
            if spike:
                spike['question'] = market['question']
                opportunities.append(spike)
            
            # Check for arbitrage
            arb = self.check_arbitrage(market_id)
            if arb:
                arb['question'] = market['question']
                opportunities.append(arb)
        
        return opportunities
    
    def watch(self, market_ids: List[str] = None, duration: float = None):
        """
        Watch markets continuously.
        
        Args:
            market_ids: Specific markets to watch (None = all markets)
            duration: How long to watch in seconds (None = forever)
        """
        self.running = True
        start_time = time.time()
        
        print(f"\n👀 Watching markets (poll every {self.poll_interval}s)...")
        print("   Press Ctrl+C to stop\n")
        
        try:
            while self.running:
                # Check duration
                if duration and (time.time() - start_time) > duration:
                    break
                
                # Scan for opportunities
                opportunities = self.scan_once()
                
                # Report findings
                for opp in opportunities:
                    self._report_opportunity(opp)
                    for callback in self.callbacks:
                        callback(opp)
                
                # Wait for next poll
                time.sleep(self.poll_interval)
                
        except KeyboardInterrupt:
            print("\n\n👋 Stopped watching.")
        
        self.running = False
    
    def _report_opportunity(self, opp: Dict):
        """Print opportunity to console."""
        opp_type = opp.get('type', '')
        question = opp.get('question', '')[:40]
        
        if opp_type == 'ARBITRAGE':
            print(f"💰 ARBITRAGE: {question}...")
            print(f"   YES: ${opp['yes_price']:.4f} + NO: ${opp['no_price']:.4f} = ${opp['total']:.4f}")
            print(f"   Edge: {opp['edge_pct']:.2f}%")
        
        elif opp_type in ['YES_DROP', 'NO_DROP']:
            side = 'YES' if opp_type == 'YES_DROP' else 'NO'
            print(f"📉 SPIKE: {question}...")
            print(f"   {side} dropped {opp['change_pct']:.1f}%: ${opp['old_price']:.4f} → ${opp['new_price']:.4f}")
            print(f"   Action: {opp['action']}")
    
    def stop(self):
        """Stop watching."""
        self.running = False
    
    def get_price_history(self, market_id: str) -> List[Dict]:
        """Get price history for a market."""
        if market_id not in self.price_history:
            return []
        
        return [
            {
                'timestamp': p.timestamp,
                'yes_price': p.yes_price,
                'no_price': p.no_price,
                'total': p.total
            }
            for p in self.price_history[market_id]
        ]


def quick_scan():
    """Quick scan for opportunities."""
    watcher = MarketWatcher()
    
    print("\n🔍 Quick scan for opportunities...")
    opportunities = watcher.scan_once()
    
    if opportunities:
        print(f"\n✅ Found {len(opportunities)} opportunities")
    else:
        print("\n❌ No opportunities found (market is efficient)")
    
    return opportunities


if __name__ == "__main__":
    # Quick scan
    quick_scan()
    
    # Or watch continuously for 60 seconds
    # watcher = MarketWatcher(poll_interval=5)
    # watcher.watch(duration=60)
