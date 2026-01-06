from typing import Dict, List, Any, Optional
from datetime import datetime
import math

from agents.application.trade_logger import TradeLogger


class PerformanceTracker:
    def __init__(self, logger: TradeLogger = None):
        self.logger = logger or TradeLogger()

    def get_trade_metrics(self) -> Dict[str, Any]:
        trades = self.logger.get_all_trades()
        
        if not trades:
            return {
                'total_trades': 0,
                'open_trades': 0,
                'closed_trades': 0,
                'winning_trades': 0,
                'losing_trades': 0,
                'win_rate': 0.0,
                'total_realized_pnl': 0.0,
                'average_pnl_per_trade': 0.0,
                'best_trade': 0.0,
                'worst_trade': 0.0
            }

        closed_trades = [t for t in trades if t['status'] == 'closed']
        open_trades = [t for t in trades if t['status'] == 'open']
        
        winning = [t for t in closed_trades if (t['realized_pnl'] or 0) > 0]
        losing = [t for t in closed_trades if (t['realized_pnl'] or 0) < 0]
        
        realized_pnls = [t['realized_pnl'] or 0 for t in closed_trades]
        total_realized = sum(realized_pnls)
        
        win_rate = len(winning) / len(closed_trades) * 100 if closed_trades else 0

        return {
            'total_trades': len(trades),
            'open_trades': len(open_trades),
            'closed_trades': len(closed_trades),
            'winning_trades': len(winning),
            'losing_trades': len(losing),
            'win_rate': win_rate,
            'total_realized_pnl': total_realized,
            'average_pnl_per_trade': total_realized / len(closed_trades) if closed_trades else 0,
            'best_trade': max(realized_pnls) if realized_pnls else 0,
            'worst_trade': min(realized_pnls) if realized_pnls else 0
        }

    def get_prediction_metrics(self) -> Dict[str, Any]:
        predictions = self.logger.get_all_predictions()
        
        if not predictions:
            return {
                'total_predictions': 0,
                'evaluated_predictions': 0,
                'correct_predictions': 0,
                'accuracy': 0.0,
                'average_edge': 0.0,
                'average_brier_score': None,
                'calibration': None
            }

        evaluated = [p for p in predictions if p['prediction_correct'] is not None]
        correct = [p for p in evaluated if p['prediction_correct']]
        
        edges = [p['edge'] for p in predictions if p['edge'] is not None]
        brier_scores = [p['brier_score'] for p in evaluated if p['brier_score'] is not None]

        accuracy = len(correct) / len(evaluated) * 100 if evaluated else 0
        avg_edge = sum(edges) / len(edges) if edges else 0
        avg_brier = sum(brier_scores) / len(brier_scores) if brier_scores else None

        return {
            'total_predictions': len(predictions),
            'evaluated_predictions': len(evaluated),
            'correct_predictions': len(correct),
            'accuracy': accuracy,
            'average_edge': avg_edge,
            'average_brier_score': avg_brier,
            'calibration': self._calculate_calibration(predictions)
        }

    def _calculate_calibration(self, predictions: List[Dict]) -> Optional[Dict[str, float]]:
        evaluated = [p for p in predictions 
                     if p['prediction_correct'] is not None and p['predicted_probability'] is not None]
        
        if len(evaluated) < 5:
            return None

        buckets = {i/10: [] for i in range(11)}
        
        for p in evaluated:
            prob = p['predicted_probability']
            bucket = round(prob, 1)
            bucket = min(1.0, max(0.0, bucket))
            actual = 1 if p['prediction_correct'] else 0
            buckets[bucket].append(actual)

        calibration = {}
        for bucket, outcomes in buckets.items():
            if outcomes:
                calibration[bucket] = sum(outcomes) / len(outcomes)

        return calibration

    def get_portfolio_metrics(self, initial_balance: float = 1000.0) -> Dict[str, Any]:
        snapshots = self.logger._get_all_snapshots()
        
        if not snapshots:
            return {
                'current_value': initial_balance,
                'total_return': 0.0,
                'total_return_pct': 0.0,
                'max_drawdown': 0.0,
                'sharpe_ratio': None,
                'volatility': None
            }

        latest = snapshots[0]
        values = [s['total_value'] for s in reversed(snapshots)]
        
        total_return = latest['total_value'] - initial_balance
        total_return_pct = (total_return / initial_balance) * 100
        
        max_drawdown = self._calculate_max_drawdown(values)
        
        returns = []
        for i in range(1, len(values)):
            if values[i-1] != 0:
                ret = (values[i] - values[i-1]) / values[i-1]
                returns.append(ret)

        volatility = None
        sharpe_ratio = None
        
        if len(returns) >= 2:
            mean_return = sum(returns) / len(returns)
            variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
            volatility = math.sqrt(variance)
            
            if volatility > 0:
                risk_free_rate = 0
                sharpe_ratio = (mean_return - risk_free_rate) / volatility

        return {
            'current_value': latest['total_value'],
            'total_return': total_return,
            'total_return_pct': total_return_pct,
            'max_drawdown': max_drawdown,
            'sharpe_ratio': sharpe_ratio,
            'volatility': volatility,
            'num_snapshots': len(snapshots)
        }

    def _calculate_max_drawdown(self, values: List[float]) -> float:
        if not values:
            return 0.0
        
        peak = values[0]
        max_dd = 0.0
        
        for value in values:
            if value > peak:
                peak = value
            drawdown = (peak - value) / peak if peak > 0 else 0
            max_dd = max(max_dd, drawdown)
        
        return max_dd * 100

    def generate_report(self, initial_balance: float = 1000.0) -> str:
        trade_metrics = self.get_trade_metrics()
        prediction_metrics = self.get_prediction_metrics()
        portfolio_metrics = self.get_portfolio_metrics(initial_balance)

        report = []
        report.append("\n" + "="*60)
        report.append("PAPER TRADING PERFORMANCE REPORT")
        report.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report.append("="*60)

        report.append("\n--- PORTFOLIO SUMMARY ---")
        report.append(f"Initial Balance:    ${initial_balance:,.2f}")
        report.append(f"Current Value:      ${portfolio_metrics['current_value']:,.2f}")
        report.append(f"Total Return:       ${portfolio_metrics['total_return']:,.2f} ({portfolio_metrics['total_return_pct']:+.2f}%)")
        report.append(f"Max Drawdown:       {portfolio_metrics['max_drawdown']:.2f}%")
        if portfolio_metrics['sharpe_ratio'] is not None:
            report.append(f"Sharpe Ratio:       {portfolio_metrics['sharpe_ratio']:.2f}")
        if portfolio_metrics['volatility'] is not None:
            report.append(f"Volatility:         {portfolio_metrics['volatility']*100:.2f}%")

        report.append("\n--- TRADE STATISTICS ---")
        report.append(f"Total Trades:       {trade_metrics['total_trades']}")
        report.append(f"Open Positions:     {trade_metrics['open_trades']}")
        report.append(f"Closed Trades:      {trade_metrics['closed_trades']}")
        report.append(f"Winning Trades:     {trade_metrics['winning_trades']}")
        report.append(f"Losing Trades:      {trade_metrics['losing_trades']}")
        report.append(f"Win Rate:           {trade_metrics['win_rate']:.1f}%")
        report.append(f"Total Realized P&L: ${trade_metrics['total_realized_pnl']:,.2f}")
        report.append(f"Avg P&L per Trade:  ${trade_metrics['average_pnl_per_trade']:,.2f}")
        report.append(f"Best Trade:         ${trade_metrics['best_trade']:,.2f}")
        report.append(f"Worst Trade:        ${trade_metrics['worst_trade']:,.2f}")

        report.append("\n--- AI PREDICTION ACCURACY ---")
        report.append(f"Total Predictions:  {prediction_metrics['total_predictions']}")
        report.append(f"Evaluated:          {prediction_metrics['evaluated_predictions']}")
        report.append(f"Correct:            {prediction_metrics['correct_predictions']}")
        report.append(f"Accuracy:           {prediction_metrics['accuracy']:.1f}%")
        report.append(f"Average Edge:       {prediction_metrics['average_edge']*100:+.2f}%")
        if prediction_metrics['average_brier_score'] is not None:
            report.append(f"Avg Brier Score:    {prediction_metrics['average_brier_score']:.4f}")

        report.append("\n" + "="*60)

        return "\n".join(report)

    def get_all_metrics(self, initial_balance: float = 1000.0) -> Dict[str, Any]:
        return {
            'trade_metrics': self.get_trade_metrics(),
            'prediction_metrics': self.get_prediction_metrics(),
            'portfolio_metrics': self.get_portfolio_metrics(initial_balance),
            'generated_at': datetime.now().isoformat()
        }
