from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING
import json

if TYPE_CHECKING:
    from agents.application.fill_simulator import FillSimulator, ExecutionResult, MarketConditions


@dataclass
class Position:
    market_id: str
    token_id: str
    question: str
    outcome: str
    side: str
    entry_price: float
    quantity: float
    entry_value: float
    entry_time: str
    trade_id: int
    current_price: float = 0.0
    current_value: float = 0.0
    unrealized_pnl: float = 0.0

    def update_valuation(self, current_price: float):
        self.current_price = current_price
        self.current_value = self.quantity * current_price
        if self.side == "BUY":
            self.unrealized_pnl = self.current_value - self.entry_value
        else:
            self.unrealized_pnl = self.entry_value - self.current_value

    def to_dict(self) -> dict:
        return {
            'market_id': self.market_id,
            'token_id': self.token_id,
            'question': self.question,
            'outcome': self.outcome,
            'side': self.side,
            'entry_price': self.entry_price,
            'quantity': self.quantity,
            'entry_value': self.entry_value,
            'entry_time': self.entry_time,
            'trade_id': self.trade_id,
            'current_price': self.current_price,
            'current_value': self.current_value,
            'unrealized_pnl': self.unrealized_pnl
        }


class PaperPortfolio:
    INITIAL_BALANCE = 1000.0
    LEGACY_SLIPPAGE_RATE = 0.001  # 0.1% slippage (legacy fallback)

    def __init__(
        self,
        initial_balance: float = None,
        fill_simulator: "FillSimulator" = None,
        use_realistic_fills: bool = True
    ):
        """
        Initialize the paper portfolio.

        Args:
            initial_balance: Starting cash balance
            fill_simulator: Optional FillSimulator for realistic execution
            use_realistic_fills: If True and fill_simulator provided, use realistic fills
        """
        self.initial_balance = initial_balance or self.INITIAL_BALANCE
        self.cash_balance = self.initial_balance
        self.positions: Dict[str, Position] = {}  # keyed by token_id
        self.realized_pnl = 0.0
        self.total_trades = 0
        self._fill_simulator = fill_simulator
        self._use_realistic_fills = use_realistic_fills

    @property
    def fill_simulator(self) -> Optional["FillSimulator"]:
        """Get the fill simulator, creating one if realistic fills enabled but none set."""
        if self._use_realistic_fills and self._fill_simulator is None:
            try:
                from agents.application.fill_simulator import FillSimulator
                self._fill_simulator = FillSimulator()
            except ImportError:
                self._use_realistic_fills = False
        return self._fill_simulator

    def set_fill_simulator(self, simulator: "FillSimulator"):
        """Set or replace the fill simulator."""
        self._fill_simulator = simulator
        self._use_realistic_fills = simulator is not None

    def get_total_value(self) -> float:
        positions_value = sum(p.current_value for p in self.positions.values())
        return self.cash_balance + positions_value

    def get_positions_value(self) -> float:
        return sum(p.current_value for p in self.positions.values())

    def get_total_pnl(self) -> float:
        unrealized = sum(p.unrealized_pnl for p in self.positions.values())
        return self.realized_pnl + unrealized

    def get_total_return_pct(self) -> float:
        total_value = self.get_total_value()
        return ((total_value - self.initial_balance) / self.initial_balance) * 100

    def validate_trade(self, side: str, amount: float) -> tuple[bool, str]:
        if side == "BUY":
            if amount > self.cash_balance:
                return False, f"Insufficient balance. Required: ${amount:.2f}, Available: ${self.cash_balance:.2f}"
        return True, ""

    def execute_simulated_trade(
        self,
        market_id: str,
        token_id: str,
        question: str,
        outcome: str,
        side: str,
        price: float,
        size_pct: float,
        trade_id: int,
        market_conditions: "MarketConditions" = None,
        liquidity: float = 5000,
        volume_24h: float = 10000
    ) -> Tuple[Optional[Position], Optional["ExecutionResult"]]:
        """
        Execute a simulated trade with optional realistic fill simulation.

        Args:
            market_id: Market identifier
            token_id: Token identifier
            question: Market question
            outcome: Outcome being traded
            side: "BUY" or "SELL"
            price: Market price
            size_pct: Percentage of available capital/position to trade
            trade_id: Trade identifier
            market_conditions: Optional MarketConditions for realistic fills
            liquidity: Estimated market liquidity (used if market_conditions not provided)
            volume_24h: 24h trading volume (used if market_conditions not provided)

        Returns:
            Tuple of (Position or None, ExecutionResult or None)
        """
        if side == "BUY":
            trade_amount = self.cash_balance * size_pct
        else:
            if token_id in self.positions:
                position = self.positions[token_id]
                trade_amount = position.current_value * size_pct
            else:
                return None, None

        valid, error = self.validate_trade(side, trade_amount if side == "BUY" else 0)
        if not valid:
            print(f"Trade validation failed: {error}")
            return None, None

        execution_result = None

        # Use realistic fill simulation if available
        if self._use_realistic_fills and self.fill_simulator is not None:
            execution_result = self._execute_with_fill_simulator(
                side=side,
                price=price,
                trade_amount=trade_amount,
                market_conditions=market_conditions,
                liquidity=liquidity,
                volume_24h=volume_24h
            )
            final_price = execution_result.average_price
            quantity = execution_result.total_quantity
            final_cost = execution_result.total_cost
        else:
            # Legacy fixed slippage
            if side == "BUY":
                final_price = price * (1 + self.LEGACY_SLIPPAGE_RATE)
            else:
                final_price = price * (1 - self.LEGACY_SLIPPAGE_RATE)
            quantity = trade_amount / final_price
            final_cost = quantity * final_price

        if side == "BUY":
            self.cash_balance -= final_cost

            if token_id in self.positions:
                existing = self.positions[token_id]
                total_quantity = existing.quantity + quantity
                total_value = existing.entry_value + final_cost
                avg_price = total_value / total_quantity
                existing.quantity = total_quantity
                existing.entry_value = total_value
                existing.entry_price = avg_price
                position = existing
            else:
                position = Position(
                    market_id=market_id,
                    token_id=token_id,
                    question=question,
                    outcome=outcome,
                    side=side,
                    entry_price=final_price,
                    quantity=quantity,
                    entry_value=final_cost,
                    entry_time=datetime.now().isoformat(),
                    trade_id=trade_id,
                    current_price=final_price,
                    current_value=final_cost
                )
                self.positions[token_id] = position

        else:  # SELL
            if token_id not in self.positions:
                print(f"No position to sell for token {token_id}")
                return None, execution_result

            position = self.positions[token_id]

            sell_quantity = position.quantity * size_pct
            sell_value = sell_quantity * final_price

            entry_cost_for_sold = (sell_quantity / position.quantity) * position.entry_value
            realized = sell_value - entry_cost_for_sold
            self.realized_pnl += realized

            self.cash_balance += sell_value

            remaining_quantity = position.quantity - sell_quantity
            if remaining_quantity < 0.0001:
                del self.positions[token_id]
            else:
                position.quantity = remaining_quantity
                position.entry_value -= entry_cost_for_sold
                position.update_valuation(position.current_price)

        self.total_trades += 1
        return (position if side == "BUY" else None), execution_result

    def _execute_with_fill_simulator(
        self,
        side: str,
        price: float,
        trade_amount: float,
        market_conditions: "MarketConditions" = None,
        liquidity: float = 5000,
        volume_24h: float = 10000
    ) -> "ExecutionResult":
        """
        Execute trade using the fill simulator.

        Args:
            side: "BUY" or "SELL"
            price: Market price
            trade_amount: Dollar amount to trade
            market_conditions: Optional pre-built market conditions
            liquidity: Estimated liquidity
            volume_24h: 24h volume

        Returns:
            ExecutionResult with fill details
        """
        from agents.application.fill_simulator import (
            FillSimulator, MarketConditions, create_market_conditions_from_price
        )

        # Build market conditions if not provided
        if market_conditions is None:
            market_conditions = create_market_conditions_from_price(
                price=price,
                liquidity=liquidity,
                volume_24h=volume_24h
            )

        # Calculate quantity from trade amount
        quantity = trade_amount / price

        # Simulate the execution
        return self.fill_simulator.simulate_market_order(
            side=side,
            quantity=quantity,
            conditions=market_conditions
        )

    def close_position(
        self,
        token_id: str,
        exit_price: float,
        market_conditions: "MarketConditions" = None,
        liquidity: float = 5000,
        volume_24h: float = 10000
    ) -> Tuple[float, Optional["ExecutionResult"]]:
        """
        Close an existing position.

        Args:
            token_id: Token to close position for
            exit_price: Current market price
            market_conditions: Optional MarketConditions for realistic fills
            liquidity: Estimated liquidity
            volume_24h: 24h volume

        Returns:
            Tuple of (realized_pnl, ExecutionResult or None)
        """
        if token_id not in self.positions:
            return 0.0, None

        position = self.positions[token_id]
        execution_result = None

        # Use realistic fill simulation if available
        if self._use_realistic_fills and self.fill_simulator is not None:
            trade_amount = position.quantity * exit_price
            execution_result = self._execute_with_fill_simulator(
                side="SELL",
                price=exit_price,
                trade_amount=trade_amount,
                market_conditions=market_conditions,
                liquidity=liquidity,
                volume_24h=volume_24h
            )
            final_price = execution_result.average_price
        else:
            final_price = exit_price * (1 - self.LEGACY_SLIPPAGE_RATE)

        exit_value = position.quantity * final_price

        realized = exit_value - position.entry_value
        self.realized_pnl += realized
        self.cash_balance += exit_value

        del self.positions[token_id]
        self.total_trades += 1

        return realized, execution_result

    def update_position_prices(self, price_updates: Dict[str, float]):
        for token_id, price in price_updates.items():
            if token_id in self.positions:
                self.positions[token_id].update_valuation(price)

    def get_open_positions(self) -> List[Position]:
        return list(self.positions.values())

    def get_portfolio_summary(self) -> dict:
        return {
            'cash_balance': self.cash_balance,
            'positions_value': self.get_positions_value(),
            'total_value': self.get_total_value(),
            'realized_pnl': self.realized_pnl,
            'unrealized_pnl': sum(p.unrealized_pnl for p in self.positions.values()),
            'total_pnl': self.get_total_pnl(),
            'total_return_pct': self.get_total_return_pct(),
            'num_open_positions': len(self.positions),
            'total_trades': self.total_trades
        }

    def to_dict(self) -> dict:
        return {
            'initial_balance': self.initial_balance,
            'cash_balance': self.cash_balance,
            'realized_pnl': self.realized_pnl,
            'total_trades': self.total_trades,
            'positions': {k: v.to_dict() for k, v in self.positions.items()}
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'PaperPortfolio':
        portfolio = cls(initial_balance=data['initial_balance'])
        portfolio.cash_balance = data['cash_balance']
        portfolio.realized_pnl = data['realized_pnl']
        portfolio.total_trades = data['total_trades']
        for token_id, pos_data in data.get('positions', {}).items():
            portfolio.positions[token_id] = Position(**pos_data)
        return portfolio

    def save_state(self, filepath: str):
        with open(filepath, 'w') as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load_state(cls, filepath: str) -> 'PaperPortfolio':
        with open(filepath, 'r') as f:
            data = json.load(f)
        return cls.from_dict(data)
