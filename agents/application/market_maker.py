"""
Market Maker - two-sided quoting logic with inventory controls.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from agents.application.paper_portfolio import PaperPortfolio
from agents.application.spread_model import SpreadModel


@dataclass
class MarketMakerConfig:
    price_update_threshold: float = 0.005
    size_update_threshold_pct: float = 0.1
    min_quote_price: float = 0.10
    max_quote_price: float = 0.90
    order_size_pct: float = 0.05
    max_inventory_pct: float = 0.30
    inventory_rebalance_pct: float = 0.80
    min_order_notional: float = 10.0
    max_order_notional: Optional[float] = None
    allow_short: bool = False


@dataclass
class QuoteOrder:
    market_id: str
    token_id: str
    side: str
    price: float
    size: float
    notional: float
    created_at: datetime = field(default_factory=datetime.utcnow)


class MarketMaker:
    """
    Market making strategy that generates buy/sell quotes.

    Expects market_data to include at least:
      - market_id
      - token_id
      - mid_price or price or yes_price
      - liquidity (optional)
      - volume or volume_24h (optional)
      - volatility (optional)
    """

    def __init__(
        self,
        portfolio: PaperPortfolio,
        spread_model: Optional[SpreadModel] = None,
        config: Optional[MarketMakerConfig] = None,
    ) -> None:
        self.portfolio = portfolio
        self.spread_model = spread_model or SpreadModel()
        self.config = config or MarketMakerConfig()
        self.active_orders: Dict[str, Dict[str, QuoteOrder]] = {}

    def on_market_update(self, market_data: Dict[str, Any]) -> List[QuoteOrder]:
        """Generate orders when market data updates."""
        if not self.should_update_orders(market_data):
            return []
        orders = self.generate_orders(market_data)
        if orders:
            token_id = market_data.get("token_id")
            if token_id:
                self.active_orders[token_id] = {o.side: o for o in orders}
        return orders

    def should_update_orders(self, market_data: Dict[str, Any]) -> bool:
        token_id = market_data.get("token_id")
        if not token_id:
            return False

        buy_price, sell_price, buy_size, sell_size = self._preview_quotes(market_data)
        existing = self.active_orders.get(token_id, {})

        if buy_price is None or buy_size <= 0:
            if "BUY" in existing:
                return True
        else:
            prev_buy = existing.get("BUY")
            if not prev_buy:
                return True
            if abs(prev_buy.price - buy_price) > self.config.price_update_threshold:
                return True
            if prev_buy.size and abs(prev_buy.size - buy_size) > prev_buy.size * self.config.size_update_threshold_pct:
                return True

        if sell_price is None or sell_size <= 0:
            if "SELL" in existing:
                return True
        else:
            prev_sell = existing.get("SELL")
            if not prev_sell:
                return True
            if abs(prev_sell.price - sell_price) > self.config.price_update_threshold:
                return True
            if prev_sell.size and abs(prev_sell.size - sell_size) > prev_sell.size * self.config.size_update_threshold_pct:
                return True

        return False

    def generate_orders(self, market_data: Dict[str, Any]) -> List[QuoteOrder]:
        market_id = market_data.get("market_id")
        token_id = market_data.get("token_id")
        if not market_id or not token_id:
            return []

        buy_price, sell_price, buy_size, sell_size = self._preview_quotes(market_data)
        orders: List[QuoteOrder] = []

        if buy_price is not None and buy_size > 0:
            orders.append(
                QuoteOrder(
                    market_id=market_id,
                    token_id=token_id,
                    side="BUY",
                    price=buy_price,
                    size=buy_size,
                    notional=buy_price * buy_size,
                )
            )
        if sell_price is not None and sell_size > 0:
            orders.append(
                QuoteOrder(
                    market_id=market_id,
                    token_id=token_id,
                    side="SELL",
                    price=sell_price,
                    size=sell_size,
                    notional=sell_price * sell_size,
                )
            )

        return orders

    def _preview_quotes(
        self, market_data: Dict[str, Any]
    ) -> Tuple[Optional[float], Optional[float], float, float]:
        mid_price = self._get_mid_price(market_data)
        if mid_price is None:
            return None, None, 0.0, 0.0

        order_notional = self._get_target_notional()
        if order_notional < self.config.min_order_notional:
            return None, None, 0.0, 0.0

        liquidity = float(market_data.get("liquidity") or 0)
        volume = float(market_data.get("volume_24h") or market_data.get("volume") or 0)
        volatility = float(market_data.get("volatility") or 0)

        spread = self.spread_model.calculate_spread(
            liquidity=liquidity,
            volume_24h=volume,
            order_size=order_notional,
            volatility=volatility,
            timestamp=market_data.get("timestamp"),
        )

        buy_price = max(0.01, mid_price - spread / 2)
        sell_price = min(0.99, mid_price + spread / 2)

        if buy_price < self.config.min_quote_price:
            buy_price = None
        if sell_price > self.config.max_quote_price:
            sell_price = None

        token_id = market_data.get("token_id")
        buy_notional = self._limit_buy_notional(token_id, order_notional) if buy_price else 0.0
        sell_notional = self._limit_sell_notional(token_id, order_notional) if sell_price else 0.0

        buy_size = buy_notional / buy_price if buy_price and buy_notional > 0 else 0.0
        sell_size = sell_notional / sell_price if sell_price and sell_notional > 0 else 0.0

        return buy_price, sell_price, buy_size, sell_size

    def _get_mid_price(self, market_data: Dict[str, Any]) -> Optional[float]:
        if "mid_price" in market_data:
            return float(market_data["mid_price"])
        if "price" in market_data:
            return float(market_data["price"])
        if "yes_price" in market_data:
            return float(market_data["yes_price"])
        if "outcome_prices" in market_data:
            prices = market_data.get("outcome_prices") or []
            if isinstance(prices, list) and prices:
                return float(prices[0])
        return None

    def _get_target_notional(self) -> float:
        target = self.portfolio.cash_balance * self.config.order_size_pct
        if self.config.max_order_notional is not None:
            target = min(target, self.config.max_order_notional)
        return target

    def _get_position_value(self, token_id: Optional[str]) -> float:
        if not token_id:
            return 0.0
        position = self.portfolio.positions.get(token_id)
        if not position:
            return 0.0
        if position.current_value:
            return position.current_value
        if position.current_price:
            return position.current_price * position.quantity
        if position.entry_value:
            return position.entry_value
        return position.quantity * position.entry_price

    def _limit_buy_notional(self, token_id: Optional[str], notional: float) -> float:
        total_value = self.portfolio.get_total_value()
        max_position_notional = total_value * self.config.max_inventory_pct
        if max_position_notional <= 0:
            return 0.0

        current_value = self._get_position_value(token_id)
        if max_position_notional > 0:
            exposure_pct = current_value / max_position_notional
            if exposure_pct >= self.config.inventory_rebalance_pct:
                return 0.0

        capacity = max_position_notional - current_value
        if capacity <= 0:
            return 0.0
        return min(notional, capacity)

    def _limit_sell_notional(self, token_id: Optional[str], notional: float) -> float:
        if self.config.allow_short:
            return notional

        current_value = self._get_position_value(token_id)
        if current_value <= 0:
            return 0.0
        return min(notional, current_value)
