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
    python scripts/python/run_paper_trader.py --strategy market_maker --markets "id1,id2" --duration 15m
    python scripts/python/run_paper_trader.py --strategy market_maker --market-ids "123,456" --duration 15m

New Multi-Strategy Commands:
    python scripts/python/run_paper_trader.py fullset   - Full-set arbitrage (Dutch Book) on multi-outcome markets
    python scripts/python/run_paper_trader.py endgame   - Endgame sweeps (buy 95-99% certain outcomes)
    python scripts/python/run_paper_trader.py oracle    - Oracle timing exploit (monitor Binance prices)
    python scripts/python/run_paper_trader.py rewards   - View holding rewards summary (4% APY)

Strategies:
    --strategy ai        - AI-driven prediction trades (default)
    --strategy arbitrage - Risk-free arbitrage trades (YES+NO < $1)
    --strategy gabagool  - Gabagool strategy (buy both sides cheap)
    --strategy mixed     - Arbitrage first, then AI trades
    --strategy market_maker - Market making with two-sided quotes
"""

import sys
import argparse
import json
from typing import Any, Dict, List, Optional, Tuple, Union
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from agents.application.paper_trader import PaperTrader
from agents.application.performance_tracker import PerformanceTracker
from agents.application.arbitrage_engine import print_opportunities
from agents.application.gabagool_trader import print_positions as print_gabagool_positions
from agents.application.market_maker import MarketMakerConfig
from agents.polymarket.gamma import GammaMarketClient

# New strategy imports
from agents.application.fullset_arbitrage import (
    FullSetArbitrageEngine,
    print_fullset_opportunities
)
from agents.application.endgame_sweeps import (
    EndgameSweepEngine,
    print_endgame_opportunities
)
from agents.application.oracle_timing import (
    OracleTimingEngine,
    print_oracle_opportunities
)
from agents.application.rewards_tracker import (
    HoldingRewardsTracker,
    print_rewards_summary,
    print_eligible_markets,
    print_eligible_positions
)


def _coerce_float(value: Optional[object]) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_outcome_prices(raw: Optional[object]) -> List[float]:
    if raw is None:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return []
    if not isinstance(raw, list):
        return []
    prices: List[float] = []
    for price in raw:
        try:
            prices.append(float(price))
        except (TypeError, ValueError):
            continue
    return prices


def _extract_market_volume(market: Dict[str, Any]) -> Optional[float]:
    for key in ("volume24hr", "volume24h", "volume_24h", "volume", "volumeUsd", "volumeUSD"):
        volume = _coerce_float(market.get(key))
        if volume is not None:
            return volume
    return None


def _extract_market_id(market: Dict[str, Any]) -> Optional[str]:
    for key in ("id", "market_id", "marketId"):
        market_id = market.get(key)
        if market_id is not None:
            return str(market_id)
    return None


def filter_profitable_markets(
    min_spread: float = 0.025,
    max_spread: float = 0.10,
    min_volume: float = 10000,
    max_volume: float = 1000000,
    limit: int = 5,
    page_size: int = 100,
    return_details: bool = False,
) -> Union[List[str], Tuple[List[str], List[Dict[str, Any]]]]:
    """Fetch active CLOB markets and filter by spread and volume."""
    gamma = GammaMarketClient()
    selected_ids: List[str] = []
    selected_details: List[Dict[str, Any]] = []
    offset = 0
    max_markets_to_scan = 500
    markets_scanned = 0

    while len(selected_ids) < limit and markets_scanned < max_markets_to_scan:
        params = {
            "active": True,
            "closed": False,
            "archived": False,
            "enableOrderBook": True,
            "limit": page_size,
            "offset": offset,
        }
        try:
            markets = gamma.get_markets(querystring_params=params)
        except Exception as exc:
            print(f"Failed to fetch markets: {exc}")
            break

        if not markets:
            break

        markets_scanned += len(markets)

        for market in markets:
            if market.get("active") is False or market.get("closed") is True or market.get("archived") is True:
                continue

            enable_order_book = market.get("enableOrderBook")
            if enable_order_book is None:
                enable_order_book = market.get("enable_order_book")
            if enable_order_book is False:
                continue

            market_id = _extract_market_id(market)
            if not market_id:
                continue

            volume = _extract_market_volume(market)
            if volume is None or volume < min_volume or volume > max_volume:
                continue

            outcome_prices = _parse_outcome_prices(market.get("outcomePrices") or market.get("outcome_prices"))
            if len(outcome_prices) < 2:
                continue

            yes_price = outcome_prices[0]
            no_price = outcome_prices[1]
            spread_abs = abs(1.0 - (yes_price + no_price))
            spread_pct = spread_abs / 0.5
            if spread_pct < min_spread or spread_pct > max_spread:
                continue

            selected_ids.append(market_id)
            selected_details.append(
                {
                    "market_id": market_id,
                    "spread": spread_abs,
                    "spread_pct": spread_pct,
                    "volume": volume,
                }
            )
            if len(selected_ids) >= limit:
                break

        print(f"Scanned {markets_scanned} markets, found {len(selected_ids)} matching...")

        if len(markets) < page_size:
            break
        if markets_scanned >= max_markets_to_scan:
            print(f"Reached scan limit ({max_markets_to_scan} markets)")
            break
        offset += page_size

    if return_details:
        return selected_ids, selected_details
    return selected_ids


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

    elif strategy == 'fullset':
        print("\n🔄 Running FULL-SET ARBITRAGE (Dutch Book)...")
        opportunities = trader.fullset_engine.scan_all_events(limit=args.count * 3)

        if not opportunities:
            print("   No full-set arbitrage opportunities found")
        else:
            for opp in opportunities[:args.count]:
                if trader.portfolio.cash_balance < 50:
                    print(f"\n   Low cash (${trader.portfolio.cash_balance:.2f}), stopping")
                    break

                budget = min(100, trader.portfolio.cash_balance * 0.15)
                trade = trader.fullset_engine.calculate_fullset_trade(opp, budget)

                print(f"\n   {opp.event_title[:45]}...")
                print(f"   Outcomes: {opp.num_outcomes} | Edge: {opp.edge_pct:.1f}%")
                print(f"   Buying all outcomes for ${trade['total_cost']:.2f}")

                # Execute trades for each outcome
                total_spent = 0
                for i, (outcome, price, token_id) in enumerate(zip(opp.outcomes, opp.outcome_prices, opp.token_ids)):
                    qty = trade['quantities'][i]
                    cost = trade['costs'][i]
                    if qty > 0 and price > 0 and cost > 0:
                        # Calculate size_pct based on this outcome's cost
                        size_pct = cost / trader.portfolio.cash_balance
                        position, _ = trader.portfolio.execute_simulated_trade(
                            market_id=opp.event_id,
                            token_id=token_id,
                            question=f"{opp.event_title}: {outcome}",
                            outcome=outcome,
                            side="BUY",
                            price=price,
                            size_pct=size_pct,
                            trade_id=i
                        )
                        if position:
                            total_spent += position.entry_value
                arb_trades += 1
                print(f"   Spent: ${total_spent:.2f} | Guaranteed profit: ${trade['guaranteed_profit']:.2f}")

    elif strategy == 'endgame':
        print("\n🔄 Running ENDGAME SWEEPS (near-certain outcomes)...")
        opportunities = trader.endgame_engine.scan_endgame_opportunities(
            min_price=0.90,
            max_price=0.99,
            include_sports=False,
            limit=args.count * 2
        )

        if not opportunities:
            print("   No endgame opportunities found")
        else:
            for opp in opportunities[:args.count]:
                if trader.portfolio.cash_balance < 50:
                    print(f"\n   Low cash (${trader.portfolio.cash_balance:.2f}), stopping")
                    break

                print(f"\n   {opp.question[:45]}...")
                print(f"   {opp.outcome} @ ${opp.price:.4f} | Edge: {opp.edge_pct:.1f}%")

                position, _ = trader.portfolio.execute_simulated_trade(
                    market_id=opp.market_id,
                    token_id=opp.token_id,
                    question=opp.question,
                    outcome=opp.outcome,
                    side="BUY",
                    price=opp.price,
                    size_pct=0.15,
                    trade_id=arb_trades
                )
                if position:
                    arb_trades += 1
                    print(f"   Bought {position.quantity:.2f} shares for ${position.entry_value:.2f}")

    elif strategy == 'oracle':
        print("\n🔄 Running ORACLE TIMING (price threshold exploits)...")
        opportunities = trader.oracle_engine.scan_oracle_opportunities(
            min_edge_pct=args.min_edge,
            limit=args.count * 2
        )

        if not opportunities:
            print("   No oracle timing opportunities found")
        else:
            for opp in opportunities[:args.count]:
                if trader.portfolio.cash_balance < 50:
                    print(f"\n   Low cash (${trader.portfolio.cash_balance:.2f}), stopping")
                    break

                budget = min(100, trader.portfolio.cash_balance * 0.15)
                trade = trader.oracle_engine.calculate_oracle_trade(opp, budget)

                print(f"\n   {opp.question[:45]}...")
                print(f"   {opp.asset} {opp.threshold_direction} ${opp.threshold_price:,.0f}")
                print(f"   Current: ${opp.current_price:,.2f} | PM: ${opp.polymarket_price:.4f}")

                position, _ = trader.portfolio.execute_simulated_trade(
                    market_id=opp.market_id,
                    token_id=opp.token_id,
                    question=opp.question,
                    outcome="Yes",
                    side="BUY",
                    price=opp.polymarket_price,
                    size_pct=0.15,
                    trade_id=arb_trades
                )
                if position:
                    arb_trades += 1
                    print(f"   Bought {position.quantity:.2f} shares for ${position.entry_value:.2f}")

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
    
    # 3. Save portfolio state
    trader._save_portfolio_state()

    # 4. Final summary
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


def cmd_fullset(args):
    """Scan and execute full-set (Dutch Book) arbitrage on multi-outcome markets."""
    trader = PaperTrader(initial_balance=args.balance, use_realistic_fills=getattr(args, 'realistic', False))
    engine = FullSetArbitrageEngine()

    print(f"\nScanning for full-set arbitrage (min {args.min_outcomes} outcomes, min {args.min_edge}% edge, max {args.max_days} days)...")

    opportunities = engine.find_best_opportunities(
        min_edge_pct=args.min_edge,
        min_liquidity=args.min_liquidity,
        min_outcomes=args.min_outcomes,
        max_days=args.max_days,
        limit=args.limit,
        sort_by=args.sort_by
    )

    print_fullset_opportunities(opportunities)

    # Show slippage estimates if requested
    if opportunities and args.show_slippage:
        print("\n" + "="*70)
        print("  SLIPPAGE ESTIMATES (for ${:.0f} budget per trade)".format(args.budget))
        print("="*70)
        for i, opp in enumerate(opportunities[:args.limit], 1):
            raw_profit, realistic_profit, slippage_pct = engine.estimate_realistic_edge(opp, args.budget)
            raw_return_pct = (raw_profit / args.budget) * 100
            realistic_return_pct = (realistic_profit / args.budget) * 100
            print(f"\n{i}. {opp.event_title[:50]}...")
            print(f"   Raw Profit: ${raw_profit:.2f} ({raw_return_pct:.1f}% return)")
            print(f"   Slippage Cost: {slippage_pct:.2f}%")
            print(f"   Realistic Profit: ${realistic_profit:.2f} ({realistic_return_pct:.1f}% return)")
            if realistic_profit <= 0:
                print("   WARNING: Slippage exceeds profit - trade not profitable!")
        print("="*70)

    if opportunities and args.execute > 0:
        print(f"\nExecuting top {min(args.execute, len(opportunities))} opportunities...")
        for opp in opportunities[:args.execute]:
            if trader.portfolio.cash_balance < 50:
                print(f"\nLow cash (${trader.portfolio.cash_balance:.2f}), stopping.")
                break

            budget = trader.portfolio.cash_balance * 0.15
            calc = engine.calculate_fullset_trade(opp, budget)

            print(f"\nBuying all {opp.num_outcomes} outcomes for {opp.event_title[:40]}...")
            print(f"   Budget: ${budget:.2f}")
            print(f"   Guaranteed profit: ${calc['guaranteed_profit']:.2f} ({calc['profit_pct']:.2f}%)")

            # Execute trades for each outcome
            for i, (outcome, price, _) in enumerate(zip(opp.outcomes, opp.outcome_prices, opp.token_ids)):
                qty = calc['quantities'][i]
                cost = calc['costs'][i]
                trader.portfolio.cash_balance -= cost
                print(f"      {outcome[:30]}: {qty:.2f} shares @ ${price:.4f} = ${cost:.2f}")

            trader.portfolio.total_trades += opp.num_outcomes

        summary = trader.portfolio.get_portfolio_summary()
        print(f"\nPortfolio: ${summary['total_value']:.2f} | Cash: ${summary['cash_balance']:.2f}")

    return 0


def cmd_endgame(args):
    """Scan for near-certain outcomes to sweep."""
    trader = PaperTrader(initial_balance=args.balance, use_realistic_fills=getattr(args, 'realistic', False))
    engine = EndgameSweepEngine()

    print(f"\nScanning for endgame opportunities (price {args.min_price}-{args.max_price}, max {args.max_days} days)...")

    opportunities = engine.find_best_opportunities(
        min_price=args.min_price,
        max_price=args.max_price,
        exclude_sports=not args.include_sports,
        prefer_political=True,
        min_liquidity=args.min_liquidity,
        max_days=args.max_days,
        limit=args.limit,
        sort_by=args.sort_by
    )

    print_endgame_opportunities(opportunities)

    if opportunities and args.execute > 0:
        print(f"\nExecuting top {min(args.execute, len(opportunities))} sweeps...")
        for opp in opportunities[:args.execute]:
            if trader.portfolio.cash_balance < 50:
                print(f"\nLow cash (${trader.portfolio.cash_balance:.2f}), stopping.")
                break

            budget = trader.portfolio.cash_balance * 0.1
            calc = engine.calculate_sweep_trade(opp, budget)

            print(f"\nSweeping {opp.question[:40]}...")
            print(f"   Outcome: {opp.outcome} @ ${opp.price:.4f}")
            print(f"   Buying {calc['quantity']:.2f} shares for ${calc['cost']:.2f}")
            print(f"   Expected profit: ${calc['guaranteed_profit']:.2f} ({calc['profit_pct']:.2f}%)")

            trader.portfolio.cash_balance -= calc['cost']
            trader.portfolio.total_trades += 1

        summary = trader.portfolio.get_portfolio_summary()
        print(f"\nPortfolio: ${summary['total_value']:.2f} | Cash: ${summary['cash_balance']:.2f}")

    return 0


def cmd_oracle(args):
    """Monitor oracle timing opportunities."""
    trader = PaperTrader(initial_balance=args.balance, use_realistic_fills=getattr(args, 'realistic', False))
    engine = OracleTimingEngine()

    if args.monitor:
        print(f"\nMonitoring for oracle timing opportunities ({args.duration}s)...")
        print("Press Ctrl+C to stop early\n")

        opportunities = engine.monitor_and_alert(
            poll_interval=args.poll_interval,
            duration=args.duration
        )

        if opportunities:
            print(f"\n\nFound {len(opportunities)} opportunities during monitoring:")
            print_oracle_opportunities(opportunities)
    else:
        print("\nScanning for oracle timing opportunities...")
        opportunities = engine.scan_oracle_opportunities(
            min_edge_pct=args.min_edge,
            limit=args.limit
        )

        print_oracle_opportunities(opportunities)

        if opportunities and args.execute > 0:
            print(f"\nExecuting top {min(args.execute, len(opportunities))} oracle trades...")
            for opp in opportunities[:args.execute]:
                if not opp.event_occurred:
                    print(f"   Skipping {opp.market_id}: event not occurred yet")
                    continue

                if trader.portfolio.cash_balance < 50:
                    print(f"\nLow cash (${trader.portfolio.cash_balance:.2f}), stopping.")
                    break

                budget = trader.portfolio.cash_balance * 0.1
                calc = engine.calculate_oracle_trade(opp, budget)

                print(f"\nOracle trade: {opp.question[:40]}...")
                print(f"   {opp.asset} is {opp.threshold_direction} ${opp.threshold_price:,.0f}")
                print(f"   Current: ${opp.current_price:,.2f} | Polymarket: ${opp.polymarket_price:.4f}")
                print(f"   Buying {calc['quantity']:.2f} shares for ${calc['cost']:.2f}")
                print(f"   Expected profit: ${calc['guaranteed_profit']:.2f}")

                trader.portfolio.cash_balance -= calc['cost']
                trader.portfolio.total_trades += 1

            summary = trader.portfolio.get_portfolio_summary()
            print(f"\nPortfolio: ${summary['total_value']:.2f} | Cash: ${summary['cash_balance']:.2f}")

    return 0


def cmd_rewards(args):
    """Show holding rewards summary."""
    trader = PaperTrader(initial_balance=args.balance)
    rewards_tracker = HoldingRewardsTracker(trader.portfolio)

    if args.find:
        print("\nFinding reward-eligible markets...")
        markets = rewards_tracker.find_reward_eligible_markets(
            min_liquidity=args.min_liquidity,
            limit=args.limit
        )
        print_eligible_markets(markets)

        # Show projected rewards calculator
        print("\n" + "="*50)
        print("  PROJECTED REWARDS CALCULATOR")
        print("="*50)
        projection = rewards_tracker.calculate_projected_rewards(1000, hold_days=365)
        print(f"  For $1,000 investment at {projection['apy']:.1f}% APY:")
        print(f"  Daily:   ${projection['daily_reward']:.4f}")
        print(f"  Monthly: ${projection['monthly_reward']:.2f}")
        print(f"  Annual:  ${projection['annual_reward']:.2f}")
        print("="*50)
    else:
        print_rewards_summary(rewards_tracker)

        if args.verbose:
            print("\nReward-eligible positions:")
            positions = rewards_tracker.get_eligible_positions()
            print_eligible_positions(positions)

    return 0


def cmd_market_maker(args):
    """Run market making loop via WebSocket updates."""
    token_ids: List[str] = []
    if args.auto_select_markets:
        print("Auto-selecting markets with profitable spreads...")
        market_ids, details = filter_profitable_markets(
            min_spread=args.min_spread,
            max_spread=args.max_spread,
            min_volume=args.min_volume,
            max_volume=args.max_volume,
            limit=5,
            return_details=True,
        )
        if not market_ids:
            print("No markets met the selection criteria.")
            return 1
        print(f"Selected {len(market_ids)} markets:")
        for detail in details:
            spread_pct = detail.get("spread_pct")
            volume = detail.get("volume")
            spread_label = f"{spread_pct:.2%}" if spread_pct is not None else "n/a"
            if volume is not None:
                print(
                    "  - {} (Spread: {}, Volume: ${:,.0f})".format(
                        detail.get("market_id"), spread_label, volume
                    )
                )
            else:
                print(f"  - {detail.get('market_id')} (Spread: {spread_label})")
        token_ids = _resolve_token_ids_from_market_ids(",".join(market_ids))
    else:
        token_ids = _parse_token_ids(args.markets)
        token_ids += _resolve_token_ids_from_market_ids(args.market_ids)
    token_ids = _dedupe_list(token_ids)
    if not token_ids:
        print("No token ids provided. Use --markets \"id1,id2\" or --market-ids \"123,456\"")
        return 1

    duration_seconds = _parse_duration(args.duration)
    if duration_seconds <= 0:
        print("Invalid duration. Use formats like 15m, 2h, 900s")
        return 1

    trader = PaperTrader(initial_balance=args.balance, use_realistic_fills=args.realistic)

    print("\nStarting market making...")
    print(f"  Tokens: {len(token_ids)}")
    print(f"  Duration: {duration_seconds:.0f}s")
    print(f"  Realistic fills: {args.realistic}")

    mm_config = MarketMakerConfig(min_spread_pct=args.min_spread)
    results = trader.run_market_making(
        token_ids=token_ids,
        duration_seconds=duration_seconds,
        poll_interval=args.poll_interval,
        config=mm_config,
    )

    print("\nMarket making complete.")
    print(f"  Orders generated: {results.get('orders_generated', 0)}")
    print(f"  Orders executed:  {results.get('orders_executed', 0)}")
    print(f"  Portfolio value:  ${results.get('portfolio_value', 0):,.2f}")
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
    parser.add_argument(
        '--strategy',
        choices=['market_maker'],
        help='Strategy to run without a subcommand (market_maker only)'
    )
    parser.add_argument(
        '--markets',
        help='Comma-separated token ids for market making (e.g. "id1,id2")'
    )
    parser.add_argument(
        '--market-ids',
        help='Comma-separated market ids to resolve into clobTokenIds'
    )
    parser.add_argument(
        '--auto-select-markets',
        action='store_true',
        default=False,
        help='Auto-select markets based on spread and volume filters'
    )
    parser.add_argument(
        '--min-spread',
        type=float,
        default=0.025,
        help='Minimum spread as decimal (default: 0.025 = 2.5 percent)'
    )
    parser.add_argument(
        '--max-spread',
        type=float,
        default=0.10,
        help='Maximum spread as decimal (default: 0.10 = 10 percent)'
    )
    parser.add_argument(
        '--min-volume',
        type=float,
        default=10000,
        help='Minimum volume filter in USD (default: 10000)'
    )
    parser.add_argument(
        '--max-volume',
        type=float,
        default=1000000,
        help='Maximum volume filter in USD (default: 1000000)'
    )
    parser.add_argument(
        '--duration',
        default='15m',
        help='Run duration for market making (e.g. 15m, 2h, 900s)'
    )
    parser.add_argument(
        '--poll-interval',
        type=float,
        default=1.0,
        help='Polling interval in seconds for market making loop'
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
    auto_parser.add_argument('--strategy', '-s',
                             choices=['ai', 'arbitrage', 'gabagool', 'fullset', 'endgame', 'oracle', 'mixed'],
                             default='ai',
                             help='Trading strategy: ai, arbitrage, gabagool, fullset, endgame, oracle, mixed')
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

    # Full-Set Arbitrage (Dutch Book)
    fullset_parser = subparsers.add_parser('fullset', help='Full-set arbitrage (Dutch Book) on multi-outcome markets', parents=[realistic_parent])
    fullset_parser.add_argument('--min-edge', '-e', type=float, default=0.5, help='Minimum edge percent (default: 0.5)')
    fullset_parser.add_argument('--min-liquidity', '-l', type=float, default=500, help='Minimum liquidity $ (default: 500)')
    fullset_parser.add_argument('--min-outcomes', '-o', type=int, default=3, help='Minimum outcomes per event (default: 3)')
    fullset_parser.add_argument('--max-days', type=int, default=365, help='Max days until resolution (default: 365)')
    fullset_parser.add_argument('--sort-by', choices=['edge', 'annualized'], default='annualized', help='Sort by edge or annualized return (default: annualized)')
    fullset_parser.add_argument('--limit', '-n', type=int, default=10, help='Max opportunities to show (default: 10)')
    fullset_parser.add_argument('--execute', '-x', type=int, default=0, help='Execute top N opportunities (default: 0, just scan)')
    fullset_parser.add_argument('--show-slippage', action='store_true', help='Show estimated slippage for each opportunity')
    fullset_parser.add_argument('--budget', type=float, default=100, help='Budget per trade for slippage estimation (default: 100)')

    # Endgame Sweeps
    endgame_parser = subparsers.add_parser('endgame', help='Scan for endgame sweep opportunities (95-99 percent certain)', parents=[realistic_parent])
    endgame_parser.add_argument('--min-price', type=float, default=0.95, help='Minimum price (default: 0.95)')
    endgame_parser.add_argument('--max-price', type=float, default=0.99, help='Maximum price (default: 0.99)')
    endgame_parser.add_argument('--include-sports', action='store_true', help='Include sports markets (excluded by default)')
    endgame_parser.add_argument('--min-liquidity', '-l', type=float, default=500, help='Minimum liquidity $ (default: 500)')
    endgame_parser.add_argument('--max-days', type=int, default=365, help='Max days until resolution (default: 365)')
    endgame_parser.add_argument('--sort-by', choices=['edge', 'annualized'], default='annualized', help='Sort by edge or annualized return (default: annualized)')
    endgame_parser.add_argument('--limit', '-n', type=int, default=10, help='Max opportunities to show (default: 10)')
    endgame_parser.add_argument('--execute', '-x', type=int, default=0, help='Execute top N sweeps (default: 0, just scan)')

    # Oracle Timing
    oracle_parser = subparsers.add_parser('oracle', help='Oracle timing exploit (monitor external prices)', parents=[realistic_parent])
    oracle_parser.add_argument('--monitor', '-m', action='store_true', help='Continuous monitoring mode')
    oracle_parser.add_argument('--duration', '-d', type=float, default=3600, help='Monitoring duration in seconds (default: 3600)')
    oracle_parser.add_argument('--poll-interval', '-p', type=float, default=5.0, help='Poll interval in seconds (default: 5)')
    oracle_parser.add_argument('--min-edge', '-e', type=float, default=1.0, help='Minimum edge percent (default: 1.0)')
    oracle_parser.add_argument('--limit', '-n', type=int, default=10, help='Max opportunities to show (default: 10)')
    oracle_parser.add_argument('--execute', '-x', type=int, default=0, help='Execute top N oracle trades (default: 0, just scan)')

    # Holding Rewards
    rewards_parser = subparsers.add_parser('rewards', help='View holding rewards summary and eligible markets', parents=[realistic_parent])
    rewards_parser.add_argument('--find', '-f', action='store_true', help='Find reward-eligible markets')
    rewards_parser.add_argument('--verbose', '-v', action='store_true', help='Show detailed position breakdown')
    rewards_parser.add_argument('--min-liquidity', '-l', type=float, default=1000, help='Minimum liquidity $ (default: 1000)')
    rewards_parser.add_argument('--limit', '-n', type=int, default=20, help='Max markets to show (default: 20)')

    args = parser.parse_args()
    
    if args.command is None:
        if args.strategy == 'market_maker':
            return cmd_market_maker(args)
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
        # New strategy commands
        'fullset': cmd_fullset,
        'endgame': cmd_endgame,
        'oracle': cmd_oracle,
        'rewards': cmd_rewards,
    }
    
    return commands[args.command](args)


def _parse_duration(value: str) -> float:
    value = value.strip().lower()
    if value.endswith('s'):
        return float(value[:-1])
    if value.endswith('m'):
        return float(value[:-1]) * 60
    if value.endswith('h'):
        return float(value[:-1]) * 3600
    if value.endswith('d'):
        return float(value[:-1]) * 86400
    return float(value)


def _parse_market_ids(markets: Optional[str]) -> List[str]:
    if not markets:
        return []
    return [m.strip() for m in markets.split(',') if m.strip()]


def _parse_token_ids(markets: Optional[str]) -> List[str]:
    if not markets:
        return []
    normalized = []
    for raw in markets.split(','):
        token_id = _normalize_token_id(raw)
        if token_id:
            normalized.append(token_id)
    return normalized


def _resolve_token_ids_from_market_ids(market_ids: Optional[str]) -> List[str]:
    if not market_ids:
        return []

    ids = _parse_market_ids(market_ids)
    gamma = GammaMarketClient()
    token_ids: List[str] = []

    for market_id in ids:
        try:
            market = gamma.get_market(market_id)
        except Exception as exc:
            print(f"Failed to fetch market {market_id}: {exc}")
            continue
        if not market:
            continue

        clob_ids = market.get("clobTokenIds") or market.get("clob_token_ids")
        if isinstance(clob_ids, str):
            try:
                clob_ids = json.loads(clob_ids)
            except json.JSONDecodeError:
                clob_ids = []
        if not isinstance(clob_ids, list):
            clob_ids = []

        for token_id in clob_ids:
            normalized = _normalize_token_id(token_id)
            if normalized:
                token_ids.append(normalized)

    if token_ids:
        print(f"Resolved {len(token_ids)} token ids from {len(ids)} markets")
    return token_ids


def _normalize_token_id(token_id: Optional[object]) -> Optional[str]:
    if token_id is None:
        return None
    if isinstance(token_id, int):
        return hex(token_id)
    token_str = str(token_id).strip()
    if not token_str:
        return None
    if token_str.startswith("0x"):
        return token_str
    if token_str.isdigit():
        return token_str
    return token_str


def _dedupe_list(items: List[str]) -> List[str]:
    seen = set()
    deduped = []
    for item in items:
        if item not in seen:
            deduped.append(item)
            seen.add(item)
    return deduped


if __name__ == "__main__":
    sys.exit(main())
