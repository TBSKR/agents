import asyncio
import json
import threading
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

from agents.polymarket.gamma import GammaMarketClient
from agents.connectors.websocket_client import PolymarketWebSocketClient


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
        self._ws_cache: Dict[str, Dict[str, Any]] = {}
        self._ws_last_update: Dict[str, float] = {}
        self._ws_lock = threading.Lock()
        self._ws_client: Optional[PolymarketWebSocketClient] = None
        self._ws_loop: Optional[asyncio.AbstractEventLoop] = None
        self._ws_task: Optional[asyncio.Task] = None
        self._ws_thread: Optional[threading.Thread] = None

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

    def start_websocket_feed(
        self,
        token_ids: List[str],
        chunk_size: int = 25,
    ):
        """Start background WebSocket feed for real-time market updates."""
        if self._ws_thread and self._ws_thread.is_alive():
            return
        print(f"[MarketTracker] Starting WebSocket for {len(token_ids)} tokens")

        def _run_loop():
            self._ws_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._ws_loop)
            self._ws_client = PolymarketWebSocketClient(
                on_market_update=self._handle_market_update
            )
            self._ws_task = self._ws_loop.create_task(
                self._ws_client.connect_market_feed(token_ids, chunk_size=chunk_size)
            )
            try:
                self._ws_loop.run_until_complete(self._ws_task)
            except Exception as exc:
                print(f"[MarketTracker] WebSocket loop error: {exc}")
            finally:
                self._ws_loop.close()

        self._ws_thread = threading.Thread(target=_run_loop, daemon=True)
        self._ws_thread.start()

    def stop_websocket_feed(self, timeout: float = 5.0):
        """Stop the WebSocket feed if running."""
        if not self._ws_loop or not self._ws_client:
            return
        future = asyncio.run_coroutine_threadsafe(
            self._ws_client.close(), self._ws_loop
        )
        try:
            future.result(timeout=timeout)
        except Exception:
            pass

    def get_websocket_update(
        self,
        token_id: str,
        max_age_seconds: Optional[float] = 30.0,
    ) -> Optional[Dict[str, Any]]:
        """Get latest WebSocket update for a token id if still fresh."""
        with self._ws_lock:
            data = self._ws_cache.get(token_id)
            last_update = self._ws_last_update.get(token_id)

        if not data or last_update is None:
            return None
        if max_age_seconds is not None:
            age = time.time() - last_update
            if age > max_age_seconds:
                return None
        return data

    def _handle_market_update(self, data: Dict[str, Any]):
        token_id = _extract_ws_asset_id(data)
        if not token_id:
            return
        print(f"[MarketTracker] Received update for token {token_id}")
        cache_ids = _expand_ws_asset_ids(token_id)
        with self._ws_lock:
            for cache_id in cache_ids:
                if cache_id not in self._ws_cache and isinstance(data, dict):
                    print(
                        f"[MarketTracker] First update keys for {cache_id}: "
                        f"{list(data.keys())}"
                    )
                self._ws_cache[cache_id] = data
                self._ws_last_update[cache_id] = time.time()

    def clear_cache(self):
        self._cache.clear()
        with self._ws_lock:
            self._ws_cache.clear()
            self._ws_last_update.clear()

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


def _extract_ws_asset_id(data: Any) -> Optional[str]:
    if isinstance(data, dict):
        asset_id = data.get('asset_id') or data.get('assetId') or data.get('market')
        return str(asset_id) if asset_id is not None else None
    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, dict):
            asset_id = first.get('asset_id') or first.get('assetId') or first.get('market')
            return str(asset_id) if asset_id is not None else None
    return None


def _expand_ws_asset_ids(token_id: str) -> List[str]:
    ids = [token_id]
    try:
        if token_id.startswith("0x"):
            ids.append(str(int(token_id, 16)))
        elif token_id.isdigit():
            ids.append(hex(int(token_id)))
    except ValueError:
        pass
    return list(dict.fromkeys(ids))
