"""
Backtester - Backtesting engine for trading strategies.

This module provides:
- Strategy backtesting against historical data
- Multiple slippage model comparison
- Performance metrics calculation
- Walk-forward analysis
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Callable, Optional, Any
import math

from agents.application.fill_simulator import FillSimulator, create_market_conditions_from_price
from agents.application.paper_portfolio import PaperPortfolio, Position
from agents.application.data_collector import HistoricalDataCollector, PricePoint


@dataclass
class BacktestConfig:
    """Configuration for a backtest run."""
    start_date: datetime
    end_date: datetime
    initial_capital: float
    slippage_model: str = "realistic"  # "fixed", "variable", "realistic"
    fill_model: str = "partial"  # "instant", "partial"
    strategy_name: str = "default"
    position_size_pct: float = 0.1  # 10% of capital per trade
    max_positions: int = 10


@dataclass
class TradeRecord:
    """Record of a trade during backtest."""
    timestamp: datetime
    market_id: str
    side: str
    quantity: float
    entry_price: float
    exit_price: float = 0
    exit_timestamp: datetime = None
    pnl: float = 0
    slippage_bps: float = 0
    is_closed: bool = False


@dataclass
class BacktestResult:
    """Complete results of a backtest."""
    config: BacktestConfig
    total_return: float  # Percentage return
    total_pnl: float  # Dollar P&L
    sharpe_ratio: float
    max_drawdown: float  # Maximum drawdown percentage
    win_rate: float  # Percentage of winning trades
    total_trades: int
    avg_trade_pnl: float
    avg_slippage_bps: float
    equity_curve: List[float]
    trades: List[TradeRecord]
    start_value: float
    end_value: float
    duration_days: int

    def to_dict(self) -> dict:
        return {
            'config': {
                'start_date': self.config.start_date.isoformat(),
                'end_date': self.config.end_date.isoformat(),
                'initial_capital': self.config.initial_capital,
                'slippage_model': self.config.slippage_model,
                'strategy_name': self.config.strategy_name
            },
            'total_return': self.total_return,
            'total_pnl': self.total_pnl,
            'sharpe_ratio': self.sharpe_ratio,
            'max_drawdown': self.max_drawdown,
            'win_rate': self.win_rate,
            'total_trades': self.total_trades,
            'avg_trade_pnl': self.avg_trade_pnl,
            'avg_slippage_bps': self.avg_slippage_bps,
            'start_value': self.start_value,
            'end_value': self.end_value,
            'duration_days': self.duration_days
        }


@dataclass
class Signal:
    """Trading signal from a strategy."""
    market_id: str
    side: str  # "BUY" or "SELL"
    strength: float = 1.0  # 0-1, affects position sizing
    price_target: float = None
    stop_loss: float = None
    take_profit: float = None


class Backtester:
    """
    Backtests trading strategies against historical data.

    Features:
    - Multiple slippage models
    - Partial fill simulation
    - Performance metrics
    - Model comparison
    """

    def __init__(
        self,
        data_collector: HistoricalDataCollector = None,
        fill_simulator: FillSimulator = None
    ):
        """
        Initialize the backtester.

        Args:
            data_collector: Data source for historical prices
            fill_simulator: Simulator for order execution
        """
        self.data_collector = data_collector or HistoricalDataCollector()
        self.fill_simulator = fill_simulator or FillSimulator()

    def run_backtest(
        self,
        config: BacktestConfig,
        strategy_func: Callable[[Dict, PaperPortfolio], List[Signal]],
        price_data: Dict[str, List[PricePoint]] = None
    ) -> BacktestResult:
        """
        Run a backtest with the given configuration and strategy.

        Args:
            config: Backtest configuration
            strategy_func: Function that takes market state and returns signals
                           Signature: (market_state: Dict, portfolio: PaperPortfolio) -> List[Signal]
            price_data: Optional pre-loaded price data

        Returns:
            BacktestResult with complete metrics
        """
        # Initialize portfolio based on slippage model
        use_realistic = config.slippage_model in ["variable", "realistic"]
        portfolio = PaperPortfolio(
            initial_balance=config.initial_capital,
            fill_simulator=self.fill_simulator if use_realistic else None,
            use_realistic_fills=use_realistic
        )

        # Load price data if not provided
        if price_data is None:
            price_data = self._load_price_data(config)

        # Get all timestamps
        all_timestamps = self._get_all_timestamps(price_data, config)

        # Initialize tracking
        equity_curve = [config.initial_capital]
        trades: List[TradeRecord] = []
        active_trades: Dict[str, TradeRecord] = {}

        # Process each timestamp
        for timestamp in all_timestamps:
            # Build market state at this timestamp
            market_state = self._build_market_state(price_data, timestamp)

            if not market_state:
                continue

            # Update position prices
            self._update_position_prices(portfolio, market_state)

            # Get strategy signals
            signals = strategy_func(market_state, portfolio)

            # Process signals
            for signal in signals:
                if signal.market_id not in market_state:
                    continue

                current_price = market_state[signal.market_id]['price']

                if signal.side == "BUY":
                    trade = self._execute_buy(
                        portfolio, signal, current_price, timestamp, config
                    )
                    if trade:
                        trades.append(trade)
                        active_trades[signal.market_id] = trade

                elif signal.side == "SELL":
                    if signal.market_id in active_trades:
                        self._execute_sell(
                            portfolio, active_trades[signal.market_id],
                            current_price, timestamp
                        )
                        del active_trades[signal.market_id]

            # Record equity
            equity_curve.append(portfolio.get_total_value())

        # Close remaining positions at final prices
        self._close_remaining_positions(portfolio, active_trades, price_data, config.end_date)

        # Calculate metrics
        result = self._calculate_metrics(config, portfolio, equity_curve, trades)

        return result

    def _load_price_data(
        self,
        config: BacktestConfig
    ) -> Dict[str, List[PricePoint]]:
        """Load price data for all markets in date range."""
        markets = self.data_collector.get_markets_with_data()
        price_data = {}

        for market_id in markets:
            history = self.data_collector.get_price_history(
                market_id=market_id,
                start_date=config.start_date,
                end_date=config.end_date
            )
            if history:
                price_data[market_id] = history

        return price_data

    def _get_all_timestamps(
        self,
        price_data: Dict[str, List[PricePoint]],
        config: BacktestConfig
    ) -> List[datetime]:
        """Get sorted list of all unique timestamps."""
        timestamps = set()

        for market_id, history in price_data.items():
            for point in history:
                if config.start_date <= point.timestamp <= config.end_date:
                    timestamps.add(point.timestamp)

        return sorted(timestamps)

    def _build_market_state(
        self,
        price_data: Dict[str, List[PricePoint]],
        timestamp: datetime
    ) -> Dict[str, Dict]:
        """Build market state at a specific timestamp."""
        state = {}

        for market_id, history in price_data.items():
            # Find most recent price at or before timestamp
            latest = None
            for point in history:
                if point.timestamp <= timestamp:
                    latest = point
                else:
                    break

            if latest:
                state[market_id] = {
                    'price': latest.price,
                    'volume': latest.volume,
                    'liquidity': latest.liquidity,
                    'timestamp': latest.timestamp
                }

        return state

    def _update_position_prices(
        self,
        portfolio: PaperPortfolio,
        market_state: Dict[str, Dict]
    ):
        """Update portfolio position prices from market state."""
        price_updates = {}

        for position in portfolio.get_open_positions():
            if position.market_id in market_state:
                price_updates[position.token_id] = market_state[position.market_id]['price']

        portfolio.update_position_prices(price_updates)

    def _execute_buy(
        self,
        portfolio: PaperPortfolio,
        signal: Signal,
        price: float,
        timestamp: datetime,
        config: BacktestConfig
    ) -> Optional[TradeRecord]:
        """Execute a buy trade."""
        # Check position limits
        if len(portfolio.positions) >= config.max_positions:
            return None

        # Calculate position size
        size_pct = config.position_size_pct * signal.strength
        trade_amount = portfolio.cash_balance * size_pct

        if trade_amount < 1:  # Minimum trade size
            return None

        # Execute trade
        position, execution_result = portfolio.execute_simulated_trade(
            market_id=signal.market_id,
            token_id=signal.market_id,  # Using market_id as token_id for simplicity
            question="",
            outcome="YES",
            side="BUY",
            price=price,
            size_pct=size_pct,
            trade_id=len(portfolio.positions)
        )

        if position is None:
            return None

        slippage = execution_result.slippage_bps if execution_result else 10  # Default 10 bps

        return TradeRecord(
            timestamp=timestamp,
            market_id=signal.market_id,
            side="BUY",
            quantity=position.quantity,
            entry_price=position.entry_price,
            slippage_bps=slippage
        )

    def _execute_sell(
        self,
        portfolio: PaperPortfolio,
        trade: TradeRecord,
        price: float,
        timestamp: datetime
    ):
        """Execute a sell trade and update trade record."""
        pnl, execution_result = portfolio.close_position(
            token_id=trade.market_id,
            exit_price=price
        )

        trade.exit_price = price
        trade.exit_timestamp = timestamp
        trade.pnl = pnl
        trade.is_closed = True

        if execution_result:
            trade.slippage_bps = (trade.slippage_bps + execution_result.slippage_bps) / 2

    def _close_remaining_positions(
        self,
        portfolio: PaperPortfolio,
        active_trades: Dict[str, TradeRecord],
        price_data: Dict[str, List[PricePoint]],
        end_date: datetime
    ):
        """Close all remaining positions at final prices."""
        for market_id, trade in active_trades.items():
            if market_id in price_data and price_data[market_id]:
                final_price = price_data[market_id][-1].price
                self._execute_sell(portfolio, trade, final_price, end_date)

    def _calculate_metrics(
        self,
        config: BacktestConfig,
        portfolio: PaperPortfolio,
        equity_curve: List[float],
        trades: List[TradeRecord]
    ) -> BacktestResult:
        """Calculate backtest performance metrics."""
        start_value = config.initial_capital
        end_value = portfolio.get_total_value()

        # Total return
        total_return = ((end_value - start_value) / start_value) * 100
        total_pnl = end_value - start_value

        # Win rate
        closed_trades = [t for t in trades if t.is_closed]
        winning_trades = [t for t in closed_trades if t.pnl > 0]
        win_rate = (len(winning_trades) / len(closed_trades) * 100) if closed_trades else 0

        # Average trade P&L
        avg_trade_pnl = sum(t.pnl for t in closed_trades) / len(closed_trades) if closed_trades else 0

        # Average slippage
        avg_slippage = sum(t.slippage_bps for t in trades) / len(trades) if trades else 0

        # Max drawdown
        max_drawdown = self._calculate_max_drawdown(equity_curve)

        # Sharpe ratio (simplified)
        sharpe_ratio = self._calculate_sharpe_ratio(equity_curve)

        # Duration
        duration_days = (config.end_date - config.start_date).days

        return BacktestResult(
            config=config,
            total_return=total_return,
            total_pnl=total_pnl,
            sharpe_ratio=sharpe_ratio,
            max_drawdown=max_drawdown,
            win_rate=win_rate,
            total_trades=len(trades),
            avg_trade_pnl=avg_trade_pnl,
            avg_slippage_bps=avg_slippage,
            equity_curve=equity_curve,
            trades=trades,
            start_value=start_value,
            end_value=end_value,
            duration_days=duration_days
        )

    def _calculate_max_drawdown(self, equity_curve: List[float]) -> float:
        """Calculate maximum drawdown from equity curve."""
        if not equity_curve:
            return 0

        peak = equity_curve[0]
        max_dd = 0

        for value in equity_curve:
            if value > peak:
                peak = value
            drawdown = (peak - value) / peak if peak > 0 else 0
            max_dd = max(max_dd, drawdown)

        return max_dd * 100

    def _calculate_sharpe_ratio(
        self,
        equity_curve: List[float],
        risk_free_rate: float = 0.02
    ) -> float:
        """Calculate Sharpe ratio from equity curve."""
        if len(equity_curve) < 2:
            return 0

        # Calculate returns
        returns = []
        for i in range(1, len(equity_curve)):
            if equity_curve[i - 1] > 0:
                ret = (equity_curve[i] - equity_curve[i - 1]) / equity_curve[i - 1]
                returns.append(ret)

        if not returns:
            return 0

        # Calculate mean and std
        mean_return = sum(returns) / len(returns)
        variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
        std_return = math.sqrt(variance) if variance > 0 else 0

        if std_return == 0:
            return 0

        # Annualize (assume daily returns)
        annual_factor = math.sqrt(252)
        annualized_return = mean_return * 252
        annualized_std = std_return * annual_factor

        sharpe = (annualized_return - risk_free_rate) / annualized_std

        return sharpe

    def compare_slippage_models(
        self,
        strategy_func: Callable,
        config: BacktestConfig,
        models: List[str] = None
    ) -> Dict[str, BacktestResult]:
        """
        Compare strategy performance across different slippage models.

        Args:
            strategy_func: Strategy function to test
            config: Base configuration
            models: List of slippage models to test

        Returns:
            Dict mapping model name to BacktestResult
        """
        if models is None:
            models = ["fixed", "variable", "realistic"]

        results = {}

        for model in models:
            model_config = BacktestConfig(
                start_date=config.start_date,
                end_date=config.end_date,
                initial_capital=config.initial_capital,
                slippage_model=model,
                fill_model=config.fill_model,
                strategy_name=f"{config.strategy_name}_{model}",
                position_size_pct=config.position_size_pct,
                max_positions=config.max_positions
            )

            result = self.run_backtest(model_config, strategy_func)
            results[model] = result

        return results


def simple_momentum_strategy(market_state: Dict, portfolio: PaperPortfolio) -> List[Signal]:
    """
    Simple momentum strategy for testing.

    Buys when price is below 0.5, sells when above 0.6.
    """
    signals = []

    for market_id, data in market_state.items():
        price = data['price']

        # Check if we have a position
        has_position = any(p.market_id == market_id for p in portfolio.get_open_positions())

        if price < 0.4 and not has_position:
            signals.append(Signal(market_id=market_id, side="BUY", strength=0.8))
        elif price > 0.6 and has_position:
            signals.append(Signal(market_id=market_id, side="SELL"))

    return signals
