from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional
import json


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
    SLIPPAGE_RATE = 0.001  # 0.1% slippage

    def __init__(self, initial_balance: float = None):
        self.initial_balance = initial_balance or self.INITIAL_BALANCE
        self.cash_balance = self.initial_balance
        self.positions: Dict[str, Position] = {}  # keyed by token_id
        self.realized_pnl = 0.0
        self.total_trades = 0

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
        trade_id: int
    ) -> Optional[Position]:
        if side == "BUY":
            trade_amount = self.cash_balance * size_pct
        else:
            if token_id in self.positions:
                position = self.positions[token_id]
                trade_amount = position.current_value * size_pct
            else:
                return None

        valid, error = self.validate_trade(side, trade_amount if side == "BUY" else 0)
        if not valid:
            print(f"Trade validation failed: {error}")
            return None

        if side == "BUY":
            final_price = price * (1 + self.SLIPPAGE_RATE)
            quantity = trade_amount / final_price
            final_cost = quantity * final_price

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
                return None

            position = self.positions[token_id]
            final_price = price * (1 - self.SLIPPAGE_RATE)
            
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
        return position if side == "BUY" else None

    def close_position(self, token_id: str, exit_price: float) -> float:
        if token_id not in self.positions:
            return 0.0

        position = self.positions[token_id]
        final_price = exit_price * (1 - self.SLIPPAGE_RATE)
        exit_value = position.quantity * final_price
        
        realized = exit_value - position.entry_value
        self.realized_pnl += realized
        self.cash_balance += exit_value
        
        del self.positions[token_id]
        self.total_trades += 1
        
        return realized

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
