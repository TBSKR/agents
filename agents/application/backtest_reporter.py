"""
Backtest Reporter - Generates reports from backtest results.

This module provides:
- HTML report generation
- Strategy comparison
- Slippage impact analysis
- Performance visualization data
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List
import json

from agents.application.backtester import BacktestResult


@dataclass
class SlippageAnalysis:
    """Analysis of slippage impact on performance."""
    fixed_return: float
    realistic_return: float
    return_difference: float
    return_difference_pct: float
    fixed_avg_slippage: float
    realistic_avg_slippage: float
    slippage_multiplier: float
    recommendation: str


class BacktestReporter:
    """
    Generates reports from backtest results.

    Features:
    - HTML report generation
    - Multiple strategy comparison
    - Slippage impact analysis
    """

    def __init__(self):
        """Initialize the reporter."""
        pass

    def generate_html_report(
        self,
        result: BacktestResult,
        output_path: str = None
    ) -> str:
        """
        Generate an HTML report for a backtest result.

        Args:
            result: BacktestResult to report on
            output_path: Optional path to save HTML file

        Returns:
            HTML string
        """
        html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Backtest Report - {result.config.strategy_name}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }}
        .container {{ max-width: 1200px; margin: 0 auto; background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        h1 {{ color: #333; border-bottom: 2px solid #4CAF50; padding-bottom: 10px; }}
        h2 {{ color: #555; margin-top: 30px; }}
        .metrics-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 15px; margin: 20px 0; }}
        .metric-card {{ background: #f9f9f9; padding: 15px; border-radius: 6px; text-align: center; }}
        .metric-value {{ font-size: 24px; font-weight: bold; color: #333; }}
        .metric-label {{ font-size: 12px; color: #666; margin-top: 5px; }}
        .positive {{ color: #4CAF50; }}
        .negative {{ color: #f44336; }}
        table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
        th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }}
        th {{ background: #f5f5f5; font-weight: bold; }}
        .config-table {{ max-width: 500px; }}
        .equity-chart {{ height: 300px; background: #f9f9f9; border-radius: 6px; padding: 20px; margin: 20px 0; }}
        .footer {{ margin-top: 40px; padding-top: 20px; border-top: 1px solid #ddd; color: #666; font-size: 12px; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Backtest Report</h1>
        <p><strong>Strategy:</strong> {result.config.strategy_name}</p>
        <p><strong>Period:</strong> {result.config.start_date.strftime('%Y-%m-%d')} to {result.config.end_date.strftime('%Y-%m-%d')} ({result.duration_days} days)</p>

        <h2>Performance Summary</h2>
        <div class="metrics-grid">
            <div class="metric-card">
                <div class="metric-value {'positive' if result.total_return >= 0 else 'negative'}">{result.total_return:.2f}%</div>
                <div class="metric-label">Total Return</div>
            </div>
            <div class="metric-card">
                <div class="metric-value {'positive' if result.total_pnl >= 0 else 'negative'}">${result.total_pnl:,.2f}</div>
                <div class="metric-label">Total P&L</div>
            </div>
            <div class="metric-card">
                <div class="metric-value">{result.sharpe_ratio:.2f}</div>
                <div class="metric-label">Sharpe Ratio</div>
            </div>
            <div class="metric-card">
                <div class="metric-value negative">{result.max_drawdown:.2f}%</div>
                <div class="metric-label">Max Drawdown</div>
            </div>
            <div class="metric-card">
                <div class="metric-value">{result.win_rate:.1f}%</div>
                <div class="metric-label">Win Rate</div>
            </div>
            <div class="metric-card">
                <div class="metric-value">{result.total_trades}</div>
                <div class="metric-label">Total Trades</div>
            </div>
            <div class="metric-card">
                <div class="metric-value">${result.avg_trade_pnl:.2f}</div>
                <div class="metric-label">Avg Trade P&L</div>
            </div>
            <div class="metric-card">
                <div class="metric-value">{result.avg_slippage_bps:.1f} bps</div>
                <div class="metric-label">Avg Slippage</div>
            </div>
        </div>

        <h2>Configuration</h2>
        <table class="config-table">
            <tr><td><strong>Initial Capital</strong></td><td>${result.config.initial_capital:,.2f}</td></tr>
            <tr><td><strong>Final Value</strong></td><td>${result.end_value:,.2f}</td></tr>
            <tr><td><strong>Slippage Model</strong></td><td>{result.config.slippage_model}</td></tr>
            <tr><td><strong>Fill Model</strong></td><td>{result.config.fill_model}</td></tr>
            <tr><td><strong>Position Size</strong></td><td>{result.config.position_size_pct * 100:.0f}%</td></tr>
            <tr><td><strong>Max Positions</strong></td><td>{result.config.max_positions}</td></tr>
        </table>

        <h2>Equity Curve Data</h2>
        <div class="equity-chart">
            <pre>{self._format_equity_sparkline(result.equity_curve)}</pre>
            <p>Start: ${result.equity_curve[0]:,.2f} | End: ${result.equity_curve[-1]:,.2f} | High: ${max(result.equity_curve):,.2f} | Low: ${min(result.equity_curve):,.2f}</p>
        </div>

        <h2>Trade Summary</h2>
        <table>
            <tr>
                <th>Metric</th>
                <th>Value</th>
            </tr>
            <tr><td>Total Trades</td><td>{result.total_trades}</td></tr>
            <tr><td>Winning Trades</td><td>{int(result.win_rate * result.total_trades / 100)}</td></tr>
            <tr><td>Losing Trades</td><td>{result.total_trades - int(result.win_rate * result.total_trades / 100)}</td></tr>
            <tr><td>Average Win</td><td>${self._calc_avg_win(result.trades):.2f}</td></tr>
            <tr><td>Average Loss</td><td>${self._calc_avg_loss(result.trades):.2f}</td></tr>
        </table>

        <div class="footer">
            <p>Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
            <p>Polymarket Trading Agent Backtest Report</p>
        </div>
    </div>
</body>
</html>
"""
        if output_path:
            with open(output_path, 'w') as f:
                f.write(html)

        return html

    def _format_equity_sparkline(self, equity_curve: List[float], width: int = 60) -> str:
        """Create a simple ASCII sparkline of the equity curve."""
        if not equity_curve:
            return ""

        # Sample equity curve to fit width
        step = max(1, len(equity_curve) // width)
        sampled = equity_curve[::step][:width]

        min_val = min(sampled)
        max_val = max(sampled)
        range_val = max_val - min_val or 1

        # Map to characters
        chars = " ▁▂▃▄▅▆▇█"
        sparkline = ""
        for val in sampled:
            idx = int((val - min_val) / range_val * (len(chars) - 1))
            sparkline += chars[idx]

        return sparkline

    def _calc_avg_win(self, trades: list) -> float:
        """Calculate average winning trade."""
        wins = [t.pnl for t in trades if t.is_closed and t.pnl > 0]
        return sum(wins) / len(wins) if wins else 0

    def _calc_avg_loss(self, trades: list) -> float:
        """Calculate average losing trade."""
        losses = [t.pnl for t in trades if t.is_closed and t.pnl < 0]
        return sum(losses) / len(losses) if losses else 0

    def compare_strategies(
        self,
        results: Dict[str, BacktestResult],
        output_path: str = None
    ) -> str:
        """
        Generate comparison report for multiple strategies.

        Args:
            results: Dict mapping strategy name to BacktestResult
            output_path: Optional path to save HTML file

        Returns:
            HTML string
        """
        rows = ""
        for name, result in results.items():
            return_class = 'positive' if result.total_return >= 0 else 'negative'
            rows += f"""
            <tr>
                <td>{name}</td>
                <td class="{return_class}">{result.total_return:.2f}%</td>
                <td class="{return_class}">${result.total_pnl:,.2f}</td>
                <td>{result.sharpe_ratio:.2f}</td>
                <td class="negative">{result.max_drawdown:.2f}%</td>
                <td>{result.win_rate:.1f}%</td>
                <td>{result.total_trades}</td>
                <td>{result.avg_slippage_bps:.1f} bps</td>
            </tr>
            """

        html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Strategy Comparison Report</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }}
        .container {{ max-width: 1400px; margin: 0 auto; background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        h1 {{ color: #333; border-bottom: 2px solid #2196F3; padding-bottom: 10px; }}
        table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
        th, td {{ padding: 12px; text-align: right; border-bottom: 1px solid #ddd; }}
        th {{ background: #f5f5f5; font-weight: bold; text-align: center; }}
        td:first-child {{ text-align: left; font-weight: bold; }}
        .positive {{ color: #4CAF50; }}
        .negative {{ color: #f44336; }}
        tr:hover {{ background: #f9f9f9; }}
        .footer {{ margin-top: 40px; padding-top: 20px; border-top: 1px solid #ddd; color: #666; font-size: 12px; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Strategy Comparison Report</h1>
        <p>Comparing {len(results)} strategies</p>

        <table>
            <tr>
                <th>Strategy</th>
                <th>Return</th>
                <th>P&L</th>
                <th>Sharpe</th>
                <th>Max DD</th>
                <th>Win Rate</th>
                <th>Trades</th>
                <th>Avg Slippage</th>
            </tr>
            {rows}
        </table>

        <div class="footer">
            <p>Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        </div>
    </div>
</body>
</html>
"""
        if output_path:
            with open(output_path, 'w') as f:
                f.write(html)

        return html

    def analyze_slippage_impact(
        self,
        fixed_result: BacktestResult,
        realistic_result: BacktestResult
    ) -> SlippageAnalysis:
        """
        Analyze the impact of realistic slippage on performance.

        Args:
            fixed_result: Result with fixed slippage model
            realistic_result: Result with realistic slippage model

        Returns:
            SlippageAnalysis with detailed comparison
        """
        return_diff = fixed_result.total_return - realistic_result.total_return
        return_diff_pct = (return_diff / abs(fixed_result.total_return) * 100) if fixed_result.total_return != 0 else 0

        slippage_mult = (realistic_result.avg_slippage_bps / fixed_result.avg_slippage_bps) if fixed_result.avg_slippage_bps > 0 else 1

        # Generate recommendation
        if return_diff > 5:
            recommendation = "WARNING: Fixed slippage significantly overestimates performance. Use realistic model for accurate projections."
        elif return_diff > 2:
            recommendation = "CAUTION: Fixed slippage moderately overestimates performance. Consider realistic model for production."
        elif return_diff > 0:
            recommendation = "Fixed slippage slightly overestimates performance. Difference is within acceptable bounds."
        else:
            recommendation = "Realistic slippage model shows better performance. This is unusual - verify data quality."

        return SlippageAnalysis(
            fixed_return=fixed_result.total_return,
            realistic_return=realistic_result.total_return,
            return_difference=return_diff,
            return_difference_pct=return_diff_pct,
            fixed_avg_slippage=fixed_result.avg_slippage_bps,
            realistic_avg_slippage=realistic_result.avg_slippage_bps,
            slippage_multiplier=slippage_mult,
            recommendation=recommendation
        )

    def generate_slippage_report(
        self,
        analysis: SlippageAnalysis,
        output_path: str = None
    ) -> str:
        """
        Generate HTML report for slippage impact analysis.

        Args:
            analysis: SlippageAnalysis object
            output_path: Optional path to save HTML file

        Returns:
            HTML string
        """
        impact_class = 'negative' if analysis.return_difference > 2 else 'positive'

        html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Slippage Impact Analysis</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }}
        .container {{ max-width: 800px; margin: 0 auto; background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        h1 {{ color: #333; border-bottom: 2px solid #FF9800; padding-bottom: 10px; }}
        .comparison {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin: 20px 0; }}
        .model-card {{ padding: 20px; border-radius: 6px; text-align: center; }}
        .fixed {{ background: #e3f2fd; }}
        .realistic {{ background: #fff3e0; }}
        .value {{ font-size: 28px; font-weight: bold; }}
        .label {{ font-size: 14px; color: #666; }}
        .impact {{ padding: 20px; margin: 20px 0; border-radius: 6px; }}
        .impact.warning {{ background: #ffebee; border: 1px solid #f44336; }}
        .impact.caution {{ background: #fff8e1; border: 1px solid #ff9800; }}
        .impact.ok {{ background: #e8f5e9; border: 1px solid #4caf50; }}
        .positive {{ color: #4CAF50; }}
        .negative {{ color: #f44336; }}
        table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
        th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }}
        .footer {{ margin-top: 40px; padding-top: 20px; border-top: 1px solid #ddd; color: #666; font-size: 12px; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Slippage Impact Analysis</h1>

        <div class="comparison">
            <div class="model-card fixed">
                <div class="label">Fixed Slippage Model</div>
                <div class="value">{analysis.fixed_return:.2f}%</div>
                <div class="label">Avg Slippage: {analysis.fixed_avg_slippage:.1f} bps</div>
            </div>
            <div class="model-card realistic">
                <div class="label">Realistic Slippage Model</div>
                <div class="value">{analysis.realistic_return:.2f}%</div>
                <div class="label">Avg Slippage: {analysis.realistic_avg_slippage:.1f} bps</div>
            </div>
        </div>

        <div class="impact {'warning' if analysis.return_difference > 5 else 'caution' if analysis.return_difference > 2 else 'ok'}">
            <h3>Impact Assessment</h3>
            <p><strong>Return Difference:</strong> <span class="{impact_class}">{analysis.return_difference:.2f}%</span></p>
            <p><strong>Slippage Multiplier:</strong> {analysis.slippage_multiplier:.1f}x</p>
            <p><strong>Recommendation:</strong> {analysis.recommendation}</p>
        </div>

        <h2>Detailed Comparison</h2>
        <table>
            <tr><th>Metric</th><th>Fixed</th><th>Realistic</th><th>Difference</th></tr>
            <tr>
                <td>Total Return</td>
                <td>{analysis.fixed_return:.2f}%</td>
                <td>{analysis.realistic_return:.2f}%</td>
                <td class="{impact_class}">{analysis.return_difference:.2f}%</td>
            </tr>
            <tr>
                <td>Avg Slippage (bps)</td>
                <td>{analysis.fixed_avg_slippage:.1f}</td>
                <td>{analysis.realistic_avg_slippage:.1f}</td>
                <td>{analysis.realistic_avg_slippage - analysis.fixed_avg_slippage:.1f}</td>
            </tr>
        </table>

        <div class="footer">
            <p>Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        </div>
    </div>
</body>
</html>
"""
        if output_path:
            with open(output_path, 'w') as f:
                f.write(html)

        return html

    def export_results_json(
        self,
        results: Dict[str, BacktestResult],
        output_path: str
    ):
        """
        Export backtest results to JSON.

        Args:
            results: Dict of results to export
            output_path: Path to save JSON file
        """
        data = {
            'exported_at': datetime.now().isoformat(),
            'results': {name: result.to_dict() for name, result in results.items()}
        }

        with open(output_path, 'w') as f:
            json.dump(data, f, indent=2)
