#!/usr/bin/env python3
"""
Paper Trading CLI for Polymarket AI Agent

Usage:
    python scripts/python/run_paper_trader.py trade     - Execute a paper trade cycle
    python scripts/python/run_paper_trader.py auto      - Run multiple trades + manage positions
    python scripts/python/run_paper_trader.py scan      - Scan for arbitrage opportunities
    python scripts/python/run_paper_trader.py positions - Show Gabagool positions
    python scripts/python/run_paper_trader.py watch     - Watch markets for opportunities
    python scripts/python/run_paper_trader.py status    - Show portfolio status
    python scripts/python/run_paper_trader.py export    - Export data to CSV
    python scripts/python/run_paper_trader.py report    - Generate performance report
    python scripts/python/run_paper_trader.py update    - Update position prices
    python scripts/python/run_paper_trader.py backup    - Backup data to JSON
    
Strategies:
    --strategy ai        - AI-driven prediction trades (default)
    --strategy arbitrage - Risk-free arbitrage trades (YES+NO < $1)
    --strategy gabagool  - Gabagool strategy (buy both sides cheap)
    --strategy mixed     - Arbitrage first, then AI trades
"""

import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from agents.application.paper_trader import PaperTrader
from agents.application.performance_tracker import PerformanceTracker
from agents.application.arbitrage_engine import print_opportunities
from agents.application.gabagool_trader import print_positions as print_gabagool_positions


def cmd_trade(args):
    """Execute a paper trading cycle."""
    trader = PaperTrader(initial_balance=args.balance, use_realistic_fills=args.realistic)
    result = trader.execute_paper_trade_cycle()

    if result['success']:
        print("\nTrade completed successfully!")
        if args.realistic and result.get('execution_result'):
            exec_result = result['execution_result']
            if isinstance(exec_result, dict) and 'slippage_bps' in exec_result:
                print(f"  Slippage: {exec_result['slippage_bps']:.1f} bps")
    else:
        print(f"\nTrade failed: {result.get('error', 'Unknown error')}")

    return 0 if result['success'] else 1


def cmd_auto(args):
    """Run multiple trades and manage positions."""
    trader = PaperTrader(initial_balance=args.balance, use_realistic_fills=args.realistic)
    strategy = args.strategy
    
    print("\n" + "="*60)
    print("  AUTO-TRADING SESSION")
    print("="*60)
    print(f"  Strategy: {strategy.upper()}")
    print(f"  Trades to execute: {args.count}")
    print(f"  Take Profit: {args.take_profit}%")
    print(f"  Stop Loss: {args.stop_loss}%")
    print("="*60 + "\n")
    
    trades_executed = 0
    arb_trades = 0
    positions_closed = 0
    
    # 1. First check and close profitable positions
    print("📊 Checking existing positions...")
    positions = trader.portfolio.get_open_positions()
    
    for pos in positions:
        current_price = trader.market_tracker.get_current_price(pos.market_id, pos.outcome)
        if current_price:
            pos.update_valuation(current_price)
            
            if pos.entry_value > 0:
                return_pct = (pos.unrealized_pnl / pos.entry_value) * 100
                
                # Take profit
                if return_pct >= args.take_profit:
                    print(f"\n💰 TAKING PROFIT: {pos.question[:40]}...")
                    print(f"   Return: +{return_pct:.1f}%")
                    result = trader.close_position(pos.token_id)
                    if result['success']:
                        print(f"   Realized: ${result['realized_pnl']:.2f}")
                        positions_closed += 1
                
                # Stop loss
                elif return_pct <= -args.stop_loss:
                    print(f"\n🛑 STOP LOSS: {pos.question[:40]}...")
                    print(f"   Return: {return_pct:.1f}%")
                    result = trader.close_position(pos.token_id)
                    if result['success']:
                        print(f"   Realized: ${result['realized_pnl']:.2f}")
                        positions_closed += 1
                else:
                    print(f"   {pos.question[:35]}... P&L: {return_pct:+.1f}%")
    
    # 2. Execute trades based on strategy
    if strategy == 'gabagool':
        print("\n🔄 Running GABAGOOL strategy (buy both sides)...")
        gab_result = trader.execute_gabagool_cycle(
            max_trades=args.count,
            min_edge_pct=args.min_edge,
            budget_per_trade=50.0
        )
        arb_trades = gab_result['trades_executed']
    
    elif strategy in ['arbitrage', 'mixed']:
        print("\n🔄 Running ARBITRAGE trades (risk-free)...")
        arb_count = args.count if strategy == 'arbitrage' else max(1, args.count // 2)
        arb_result = trader.execute_arbitrage_cycle(
            max_trades=arb_count,
            min_edge_pct=args.min_edge,
            budget_pct_per_trade=0.15
        )
        arb_trades = arb_result['trades_executed']
    
    if strategy in ['ai', 'mixed']:
        ai_count = args.count if strategy == 'ai' else args.count - arb_trades
        print(f"\n🔄 Running AI trades ({ai_count} trades)...")
        
        for i in range(ai_count):
            if trader.portfolio.cash_balance < 50:
                print(f"\n⚠️  Low cash (${trader.portfolio.cash_balance:.2f}), skipping trade")
                break
                
            print(f"\n🤖 AI Trade {i+1}/{ai_count}...")
            result = trader.execute_paper_trade_cycle()
            
            if result['success']:
                trades_executed += 1
                print("✅ Position opened!")
            else:
                err = result.get('error', 'Unknown')[:60]
                print(f"⚠️  Skipped: {err}")
    
    # 3. Final summary
    summary = trader.portfolio.get_portfolio_summary()
    print("\n" + "="*60)
    print("  SESSION COMPLETE")
    print("="*60)
    print(f"  Strategy: {strategy.upper()}")
    print(f"  Arbitrage trades: {arb_trades}")
    print(f"  AI trades: {trades_executed}")
    print(f"  Positions closed: {positions_closed}")
    print(f"  Portfolio: ${summary['total_value']:.2f}")
    print(f"  P&L: ${summary['total_pnl']:.2f} ({summary['total_return_pct']:+.2f}%)")
    print(f"  Open positions: {summary['num_open_positions']}")
    print("="*60)
    
    return 0


def cmd_scan(args):
    """Scan for arbitrage opportunities."""
    trader = PaperTrader(initial_balance=args.balance, use_realistic_fills=args.realistic)
    
    print(f"\n🔍 Scanning for arbitrage opportunities (min edge: {args.min_edge}%)...")
    
    opportunities = trader.scan_arbitrage_opportunities(
        min_edge_pct=args.min_edge,
        min_liquidity=args.min_liquidity,
        limit=args.limit
    )
    
    print_opportunities(opportunities)
    
    if opportunities and args.execute:
        print(f"\n⚡ Executing top {min(args.execute, len(opportunities))} opportunities...")
        for opp in opportunities[:args.execute]:
            trader.execute_arbitrage_trade(opp, budget_pct=0.1)
    
    return 0


def cmd_status(args):
    """Show current portfolio status."""
    trader = PaperTrader(initial_balance=args.balance, use_realistic_fills=getattr(args, 'realistic', False))
    status = trader.get_status()
    
    portfolio = status['portfolio']
    positions = status['positions']
    
    print("\n" + "="*50)
    print("PORTFOLIO STATUS")
    print("="*50)
    print(f"Cash Balance:      ${portfolio['cash_balance']:,.2f}")
    print(f"Positions Value:   ${portfolio['positions_value']:,.2f}")
    print(f"Total Value:       ${portfolio['total_value']:,.2f}")
    print(f"Total P&L:         ${portfolio['total_pnl']:,.2f} ({portfolio['total_return_pct']:+.2f}%)")
    print(f"  Realized:        ${portfolio['realized_pnl']:,.2f}")
    print(f"  Unrealized:      ${portfolio['unrealized_pnl']:,.2f}")
    print(f"Open Positions:    {portfolio['num_open_positions']}")
    print(f"Total Trades:      {portfolio['total_trades']}")
    
    if positions:
        print("\n--- OPEN POSITIONS ---")
        for i, pos in enumerate(positions, 1):
            print(f"\n{i}. {pos['question'][:40]}...")
            print(f"   Outcome: {pos['outcome']} ({pos['side']})")
            print(f"   Entry:   {pos['quantity']:.2f} @ ${pos['entry_price']:.4f} = ${pos['entry_value']:.2f}")
            print(f"   Current: ${pos['current_price']:.4f} = ${pos['current_value']:.2f}")
            print(f"   P&L:     ${pos['unrealized_pnl']:+.2f}")
    
    print("="*50)
    return 0


def cmd_export(args):
    """Export data to CSV files."""
    trader = PaperTrader(initial_balance=args.balance)
    
    print("\nExporting data to CSV...")
    files = trader.export_data(format='csv')
    
    if files:
        print("\nExported files:")
        for table, filepath in files.items():
            print(f"  {table}: {filepath}")
    else:
        print("No data to export.")
    
    return 0


def cmd_backup(args):
    """Backup all data to JSON."""
    trader = PaperTrader(initial_balance=args.balance)
    
    print("\nBacking up data to JSON...")
    files = trader.export_data(format='json')
    
    if files:
        print(f"\nBackup created: {files.get('backup')}")
    else:
        print("Backup failed.")
    
    return 0


def cmd_report(args):
    """Generate performance report."""
    tracker = PerformanceTracker()
    report = tracker.generate_report(initial_balance=args.balance)
    print(report)
    return 0


def cmd_update(args):
    """Update position prices from market."""
    trader = PaperTrader(initial_balance=args.balance)
    
    print("\nUpdating position prices...")
    result = trader.update_positions()
    
    print(f"Updated {result['updated']} positions")
    
    if result['positions']:
        for pos in result['positions']:
            print(f"  {pos['outcome']}: ${pos['current_price']:.4f} (P&L: ${pos['unrealized_pnl']:+.2f})")
    
    return 0


def cmd_positions(args):
    """Show Gabagool positions."""
    trader = PaperTrader(initial_balance=args.balance)
    print_gabagool_positions(trader.gabagool)
    return 0


def cmd_watch(args):
    """Watch markets for opportunities."""
    trader = PaperTrader(initial_balance=args.balance)
    
    print(f"\n👀 Watching markets for {args.duration} seconds...")
    print("   Press Ctrl+C to stop early\n")
    
    trader.watch_markets(duration=args.duration)
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Paper Trading CLI for Polymarket AI Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    parser.add_argument(
        '--balance', '-b',
        type=float,
        default=1000.0,
        help='Initial balance for new portfolio (default: 1000)'
    )
    parser.add_argument(
        '--realistic', '-r',
        action='store_true',
        default=False,
        help='Use realistic fill simulation (variable slippage, partial fills)'
    )

    realistic_parent = argparse.ArgumentParser(add_help=False)
    realistic_parent.add_argument(
        '--realistic', '-r',
        action='store_true',
        default=False,
        help='Use realistic fill simulation (variable slippage, partial fills)'
    )

    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    subparsers.add_parser('trade', help='Execute a single paper trade', parents=[realistic_parent])
    
    auto_parser = subparsers.add_parser('auto', help='Run multiple trades + manage positions', parents=[realistic_parent])
    auto_parser.add_argument('--count', '-c', type=int, default=3, help='Number of trades to execute (default: 3)')
    auto_parser.add_argument('--take-profit', '-tp', type=float, default=20.0, help='Take profit at X%% gain (default: 20)')
    auto_parser.add_argument('--stop-loss', '-sl', type=float, default=15.0, help='Stop loss at X%% loss (default: 15)')
    auto_parser.add_argument('--strategy', '-s', choices=['ai', 'arbitrage', 'gabagool', 'mixed'], default='ai', 
                             help='Trading strategy: ai, arbitrage, gabagool (recommended), mixed')
    auto_parser.add_argument('--min-edge', '-e', type=float, default=0.5, help='Minimum arbitrage edge %% (default: 0.5)')
    
    scan_parser = subparsers.add_parser('scan', help='Scan for arbitrage opportunities', parents=[realistic_parent])
    scan_parser.add_argument('--min-edge', '-e', type=float, default=0.5, help='Minimum edge %% (default: 0.5)')
    scan_parser.add_argument('--min-liquidity', '-l', type=float, default=100, help='Minimum liquidity $ (default: 100)')
    scan_parser.add_argument('--limit', '-n', type=int, default=10, help='Max opportunities to show (default: 10)')
    scan_parser.add_argument('--execute', '-x', type=int, default=0, help='Execute top N opportunities (default: 0, just scan)')
    
    subparsers.add_parser('positions', help='Show Gabagool strategy positions', parents=[realistic_parent])
    
    watch_parser = subparsers.add_parser('watch', help='Watch markets for opportunities', parents=[realistic_parent])
    watch_parser.add_argument('--duration', '-d', type=float, default=60, help='Watch duration in seconds (default: 60)')
    
    subparsers.add_parser('status', help='Show portfolio status', parents=[realistic_parent])
    subparsers.add_parser('export', help='Export data to CSV', parents=[realistic_parent])
    subparsers.add_parser('backup', help='Backup data to JSON', parents=[realistic_parent])
    subparsers.add_parser('report', help='Generate performance report', parents=[realistic_parent])
    subparsers.add_parser('update', help='Update position prices', parents=[realistic_parent])
    
    args = parser.parse_args()
    
    if args.command is None:
        parser.print_help()
        return 1
    
    commands = {
        'trade': cmd_trade,
        'auto': cmd_auto,
        'scan': cmd_scan,
        'positions': cmd_positions,
        'watch': cmd_watch,
        'status': cmd_status,
        'export': cmd_export,
        'backup': cmd_backup,
        'report': cmd_report,
        'update': cmd_update,
    }
    
    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
