import re
import ast
import json
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple, Dict, Any, List

from agents.application.paper_portfolio import PaperPortfolio, Position
from agents.application.trade_logger import TradeLogger
from agents.application.market_tracker import MarketTracker
from agents.application.arbitrage_engine import ArbitrageEngine, ArbitrageOpportunity
from agents.application.gabagool_trader import GabagoolTrader
from agents.application.market_watcher import MarketWatcher
from agents.application.market_maker import MarketMaker, MarketMakerConfig, QuoteOrder
from agents.application.spread_model import PolymarketSpreadModel
from agents.polymarket.gamma import GammaMarketClient


class PaperTrader:
    PORTFOLIO_STATE_FILE = "portfolio_state.json"

    def __init__(self, initial_balance: float = 1000.0, use_realistic_fills: bool = False):
        self._agent = None
        self._arbitrage_engine = None
        self._gabagool = None
        self._watcher = None
        self._fill_simulator = None
        self.use_realistic_fills = use_realistic_fills

        self.gamma = GammaMarketClient()
        self.logger = TradeLogger()
        self.market_tracker = MarketTracker()

        # Initialize fill simulator if using realistic fills
        if use_realistic_fills:
            self._init_fill_simulator()

        state_path = self.logger.data_dir / self.PORTFOLIO_STATE_FILE
        if state_path.exists():
            self.portfolio = PaperPortfolio.load_state(str(state_path))
            if use_realistic_fills and self._fill_simulator:
                self.portfolio.set_fill_simulator(self._fill_simulator)
            print(f"Loaded existing portfolio: ${self.portfolio.get_total_value():.2f}")
            if use_realistic_fills:
                print("  Using REALISTIC fill simulation")
        else:
            self.portfolio = PaperPortfolio(
                initial_balance=initial_balance,
                fill_simulator=self._fill_simulator if use_realistic_fills else None,
                use_realistic_fills=use_realistic_fills
            )
            print(f"Created new portfolio with ${initial_balance:.2f}")
            if use_realistic_fills:
                print("  Using REALISTIC fill simulation")

    def _init_fill_simulator(self):
        """Initialize the fill simulator for realistic execution."""
        try:
            from agents.application.fill_simulator import FillSimulator
            self._fill_simulator = FillSimulator()
            print("Fill simulator initialized")
        except ImportError as e:
            print(f"Warning: Could not initialize fill simulator: {e}")
            self._fill_simulator = None
            self.use_realistic_fills = False

    @property
    def arbitrage_engine(self):
        if self._arbitrage_engine is None:
            self._arbitrage_engine = ArbitrageEngine()
        return self._arbitrage_engine

    @property
    def gabagool(self):
        if self._gabagool is None:
            self._gabagool = GabagoolTrader(str(self.logger.data_dir))
        return self._gabagool

    @property
    def watcher(self):
        if self._watcher is None:
            self._watcher = MarketWatcher(poll_interval=5)
        return self._watcher

    @property
    def agent(self):
        if self._agent is None:
            from agents.application.paper_executor import PaperExecutor
            self._agent = PaperExecutor()
        return self._agent

    def get_all_tradeable_events(self, limit: int = 100):
        """Fetch tradeable events using Gamma API directly (no auth required).
        
        Note: For paper trading, we include geo-restricted events since we're
        not actually executing real trades.
        """
        import httpx
        from agents.utils.objects import SimpleEvent
        
        events = []
        params = {"active": "true", "closed": "false", "archived": "false", "limit": limit}
        response = httpx.get(self.gamma.gamma_events_endpoint, params=params)
        
        if response.status_code == 200:
            for event in response.json():
                try:
                    markets = event.get("markets", [])
                    if not markets:
                        continue
                    
                    event_data = {
                        "id": int(event["id"]),
                        "ticker": event.get("ticker", ""),
                        "slug": event.get("slug", ""),
                        "title": event.get("title", ""),
                        "description": event.get("description", ""),
                        "active": event.get("active", False),
                        "closed": event.get("closed", False),
                        "archived": event.get("archived", False),
                        "new": event.get("new", False),
                        "featured": event.get("featured", False),
                        "restricted": event.get("restricted", False),
                        "end": event.get("endDate", ""),
                        "markets": ",".join([str(x["id"]) for x in markets]),
                    }
                    events.append(SimpleEvent(**event_data))
                except Exception as e:
                    pass
        return events

    def _save_portfolio_state(self):
        state_path = self.logger.data_dir / self.PORTFOLIO_STATE_FILE
        self.portfolio.save_state(str(state_path))

    def _clear_local_dbs(self):
        try:
            shutil.rmtree("local_db_events")
        except:
            pass
        try:
            shutil.rmtree("local_db_markets")
        except:
            pass

    def _parse_trade_recommendation(self, trade_output: str) -> Dict[str, Any]:
        result = {'price': None, 'size': None, 'side': None}
        
        try:
            data = trade_output.split(",")
            
            price_match = re.findall(r"\d+\.?\d*", data[0])
            if price_match:
                result['price'] = float(price_match[0])
            
            size_match = re.findall(r"\d+\.?\d*", data[1])
            if size_match:
                size = float(size_match[0])
                if size > 1:
                    if size <= 100:
                        size = size / 100.0
                    else:
                        size = 1.0
                result['size'] = max(0.0, min(size, 1.0))
            
            side_upper = trade_output.upper()
            if "BUY" in side_upper:
                result['side'] = "BUY"
            elif "SELL" in side_upper:
                result['side'] = "SELL"
                
        except Exception as e:
            print(f"Error parsing trade: {e}")
        
        return result

    def _parse_ai_prediction(self, prediction_text: str) -> Tuple[Optional[float], Optional[str]]:
        prob_pattern = r"likelihood\s*[`'\"]?(\d+\.?\d*)[`'\"]?"
        prob_match = re.search(prob_pattern, prediction_text, re.IGNORECASE)
        
        outcome_pattern = r"outcome\s*(?:of\s*)?[`'\"]?(\w+)[`'\"]?"
        outcome_match = re.search(outcome_pattern, prediction_text, re.IGNORECASE)
        
        probability = float(prob_match.group(1)) if prob_match else None
        outcome = outcome_match.group(1) if outcome_match else None
        
        return probability, outcome

    def execute_paper_trade_cycle(self) -> Dict[str, Any]:
        print("\n" + "="*60)
        print("PAPER TRADING CYCLE")
        print("="*60)
        
        result = {
            'success': False,
            'trade': None,
            'position': None,
            'error': None
        }

        try:
            self._clear_local_dbs()

            print("\n1. Fetching tradeable events...")
            events = self.get_all_tradeable_events()
            print(f"   Found {len(events)} events")

            if not events:
                result['error'] = "No tradeable events found"
                return result

            print("\n2. Filtering events with RAG...")
            filtered_events = self.agent.filter_events_with_rag(events)
            print(f"   Filtered to {len(filtered_events)} events")

            if not filtered_events:
                result['error'] = "No events passed filter"
                return result

            print("\n3. Mapping events to markets...")
            markets = self.agent.map_filtered_events_to_markets(filtered_events)
            print(f"   Found {len(markets)} markets")

            if not markets:
                result['error'] = "No markets found"
                return result

            print("\n4. Filtering markets...")
            filtered_markets = self.agent.filter_markets(markets)
            print(f"   Filtered to {len(filtered_markets)} markets")

            if not filtered_markets:
                result['error'] = "No markets passed filter"
                return result

            market = filtered_markets[0]
            market_doc = market[0].dict()
            market_meta = market_doc["metadata"]
            
            market_id = str(market_meta.get("id", ""))
            question = market_meta.get("question", "")
            outcomes = ast.literal_eval(market_meta.get("outcomes", "[]"))
            outcome_prices = ast.literal_eval(market_meta.get("outcome_prices", "[]"))
            clob_token_ids = ast.literal_eval(market_meta.get("clob_token_ids", "[]"))

            print(f"\n5. Selected market: {question[:50]}...")
            print(f"   Outcomes: {outcomes}")
            print(f"   Prices: {outcome_prices}")

            print("\n6. Getting AI prediction...")
            best_trade = self.agent.source_best_trade(market)
            print(f"   Trade recommendation: {best_trade}")

            trade_params = self._parse_trade_recommendation(best_trade)
            
            if not all([trade_params['price'], trade_params['size'], trade_params['side']]):
                result['error'] = f"Could not parse trade: {best_trade}"
                return result

            ai_prob, ai_outcome = self._parse_ai_prediction(best_trade)
            if ai_outcome is None:
                ai_outcome = outcomes[0] if trade_params['side'] == "BUY" else outcomes[1]
            
            outcome_idx = 0
            if ai_outcome and ai_outcome.lower() in [o.lower() for o in outcomes]:
                outcome_idx = [o.lower() for o in outcomes].index(ai_outcome.lower())
            
            token_id = clob_token_ids[outcome_idx] if clob_token_ids else ""
            market_price = float(outcome_prices[outcome_idx]) if outcome_prices else trade_params['price']
            
            edge = (ai_prob - market_price) if ai_prob else 0

            print(f"\n7. AI Prediction: {ai_prob} for '{ai_outcome}'")
            print(f"   Market price: {market_price}")
            print(f"   Edge: {edge:+.2%}" if ai_prob else "   Edge: N/A")

            print(f"\n8. Executing simulated {trade_params['side']}...")
            print(f"   Signal price: {trade_params['price']}")
            print(f"   Market price: {market_price}")
            print(f"   Size: {trade_params['size']*100:.1f}% of portfolio")

            snapshot = self.market_tracker.get_market_snapshot(market_id)
            liquidity = snapshot.liquidity if snapshot else 5000
            volume_24h = snapshot.volume if snapshot else 10000

            market_conditions = None
            if self.use_realistic_fills:
                try:
                    from agents.application.spread_model import PolymarketSpreadModel
                    from agents.application.fill_simulator import MarketConditions

                    spread_model = PolymarketSpreadModel()
                    spread_pct = spread_model.calculate_spread(
                        liquidity=liquidity,
                        volume_24h=volume_24h,
                        order_size=self.portfolio.cash_balance * trade_params['size'],
                        price=market_price
                    )
                    half_spread = spread_pct / 2
                    market_conditions = MarketConditions(
                        mid_price=market_price,
                        bid_price=market_price * (1 - half_spread),
                        ask_price=market_price * (1 + half_spread),
                        spread=spread_pct,
                        liquidity=liquidity,
                        volume_24h=volume_24h
                    )
                except Exception:
                    market_conditions = None

            trade_id = self.logger.log_trade(
                market_id=market_id,
                question=question,
                token_id=token_id,
                outcome=ai_outcome or outcomes[outcome_idx],
                side=trade_params['side'],
                entry_price=market_price,
                quantity=0,
                entry_value=0,
                ai_prediction=ai_prob or 0,
                market_price_at_entry=market_price,
                balance_after=self.portfolio.cash_balance
            )

            position, execution_result = self.portfolio.execute_simulated_trade(
                market_id=market_id,
                token_id=token_id,
                question=question,
                outcome=ai_outcome or outcomes[outcome_idx],
                side=trade_params['side'],
                price=market_price,
                size_pct=trade_params['size'],
                trade_id=trade_id,
                market_conditions=market_conditions,
                liquidity=liquidity,
                volume_24h=volume_24h
            )

            if position:
                from agents.application.trade_logger import sqlite3
                conn = sqlite3.connect(self.logger.db_path)
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE trades 
                    SET quantity = ?, entry_value = ?, entry_price = ?, balance_after = ?
                    WHERE id = ?
                ''', (position.quantity, position.entry_value, position.entry_price, 
                      self.portfolio.cash_balance, trade_id))
                conn.commit()
                conn.close()

            market_details = self.market_tracker.get_market_details_for_logging(market_id)
            if market_details:
                self.logger.log_market_snapshot(
                    trade_id=trade_id,
                    **market_details
                )

            if ai_prob:
                self.logger.log_ai_prediction(
                    trade_id=trade_id,
                    market_id=market_id,
                    question=question,
                    outcome=ai_outcome or outcomes[outcome_idx],
                    predicted_probability=ai_prob,
                    market_probability=market_price,
                    edge=edge,
                    reasoning=best_trade
                )

            summary = self.portfolio.get_portfolio_summary()
            self.logger.log_portfolio_snapshot(
                total_value=summary['total_value'],
                cash_balance=summary['cash_balance'],
                positions_value=summary['positions_value'],
                num_open_positions=summary['num_open_positions'],
                total_pnl=summary['total_pnl'],
                total_return_pct=summary['total_return_pct']
            )

            self._save_portfolio_state()

            print("\n" + "="*60)
            print("TRADE EXECUTED SUCCESSFULLY")
            print("="*60)
            if position:
                print(f"   Bought {position.quantity:.2f} shares @ ${position.entry_price:.4f}")
                print(f"   Total cost: ${position.entry_value:.2f}")
                if execution_result and execution_result.is_partial:
                    print(f"   Partial fill: {execution_result.fill_rate:.1f}% filled")
            print(f"   New balance: ${self.portfolio.cash_balance:.2f}")
            print(f"   Total portfolio value: ${summary['total_value']:.2f}")
            print(f"   Total P&L: ${summary['total_pnl']:.2f} ({summary['total_return_pct']:+.2f}%)")

            result['success'] = True
            result['trade'] = {
                'trade_id': trade_id,
                'market_id': market_id,
                'question': question,
                'side': trade_params['side'],
                'signal_price': trade_params['price'],
                'executed_price': position.entry_price if position else market_price,
                'size_pct': trade_params['size'],
                'ai_prediction': ai_prob,
                'market_price': market_price,
                'edge': edge
            }
            result['position'] = position.to_dict() if position else None
            result['execution_result'] = (
                {
                    'total_quantity': execution_result.total_quantity,
                    'average_price': execution_result.average_price,
                    'total_cost': execution_result.total_cost,
                    'slippage_bps': execution_result.slippage_bps,
                    'fill_rate': execution_result.fill_rate,
                    'unfilled_quantity': execution_result.unfilled_quantity,
                    'is_partial': execution_result.is_partial,
                }
                if execution_result
                else None
            )

        except Exception as e:
            result['error'] = str(e)
            print(f"\nError during trade cycle: {e}")
            import traceback
            traceback.print_exc()

        return result

    def update_positions(self) -> Dict[str, Any]:
        positions = self.portfolio.get_open_positions()
        if not positions:
            return {'updated': 0, 'positions': []}

        prices = self.market_tracker.get_prices_for_positions(positions)
        self.portfolio.update_position_prices(prices)
        
        self._save_portfolio_state()
        
        return {
            'updated': len(prices),
            'positions': [p.to_dict() for p in positions]
        }

    def get_status(self) -> Dict[str, Any]:
        self.update_positions()
        
        summary = self.portfolio.get_portfolio_summary()
        positions = [p.to_dict() for p in self.portfolio.get_open_positions()]
        
        return {
            'portfolio': summary,
            'positions': positions
        }

    def export_data(self, format: str = 'csv') -> Dict[str, str]:
        if format == 'csv':
            return self.logger.export_to_csv()
        elif format == 'json':
            filepath = self.logger.backup_to_json()
            return {'backup': filepath}
        else:
            return {}

    def close_position(self, token_id: str) -> Dict[str, Any]:
        position = self.portfolio.positions.get(token_id)
        if not position:
            return {'success': False, 'error': 'Position not found'}

        current_price = self.market_tracker.get_current_price(
            position.market_id, position.outcome
        )
        if current_price is None:
            return {'success': False, 'error': 'Could not fetch current price'}

        snapshot = self.market_tracker.get_market_snapshot(position.market_id)
        liquidity = snapshot.liquidity if snapshot else 5000
        volume_24h = snapshot.volume if snapshot else 10000

        market_conditions = None
        if self.use_realistic_fills:
            try:
                from agents.application.spread_model import PolymarketSpreadModel
                from agents.application.fill_simulator import MarketConditions

                spread_model = PolymarketSpreadModel()
                spread_pct = spread_model.calculate_spread(
                    liquidity=liquidity,
                    volume_24h=volume_24h,
                    order_size=position.quantity * current_price,
                    price=current_price
                )
                half_spread = spread_pct / 2
                market_conditions = MarketConditions(
                    mid_price=current_price,
                    bid_price=current_price * (1 - half_spread),
                    ask_price=current_price * (1 + half_spread),
                    spread=spread_pct,
                    liquidity=liquidity,
                    volume_24h=volume_24h
                )
            except Exception:
                market_conditions = None

        realized_pnl, execution_result = self.portfolio.close_position(
            token_id,
            current_price,
            market_conditions=market_conditions,
            liquidity=liquidity,
            volume_24h=volume_24h
        )
        exit_price_used = execution_result.average_price if execution_result else current_price
        
        open_trades = self.logger.get_open_trades()
        for trade in open_trades:
            if trade['token_id'] == token_id:
                self.logger.close_trade(trade['id'], exit_price_used, realized_pnl)
                break

        self._save_portfolio_state()

        return {
            'success': True,
            'realized_pnl': realized_pnl,
            'exit_price': exit_price_used
        }

    # ==================== ARBITRAGE METHODS ====================
    
    def scan_arbitrage_opportunities(
        self, 
        min_edge_pct: float = 0.5,
        min_liquidity: float = 100,
        limit: int = 10
    ) -> List[ArbitrageOpportunity]:
        """Scan for arbitrage opportunities."""
        return self.arbitrage_engine.find_best_opportunities(
            min_edge_pct=min_edge_pct,
            min_liquidity=min_liquidity,
            limit=limit
        )

    def execute_arbitrage_trade(
        self, 
        opportunity: ArbitrageOpportunity,
        budget_pct: float = 0.1
    ) -> Dict[str, Any]:
        """Execute an arbitrage trade (buy both YES and NO)."""
        
        result = {
            'success': False,
            'opportunity': opportunity.to_dict(),
            'trades': [],
            'error': None
        }
        
        # Calculate budget
        budget = self.portfolio.cash_balance * budget_pct
        if budget < 10:
            result['error'] = f"Insufficient funds: ${self.portfolio.cash_balance:.2f}"
            return result
        
        # Calculate trade quantities
        calc = self.arbitrage_engine.calculate_arbitrage_trade(opportunity, budget)
        
        print(f"\n📊 ARBITRAGE TRADE")
        print(f"   Market: {opportunity.question[:50]}...")
        print(f"   YES: ${opportunity.yes_price:.4f} | NO: ${opportunity.no_price:.4f}")
        print(f"   Edge: {opportunity.edge_pct:.2f}%")
        print(f"   Budget: ${budget:.2f}")
        
        # Execute YES trade
        yes_token_id = opportunity.token_ids[0] if opportunity.token_ids else f"{opportunity.market_id}_yes"
        yes_trade_id = self.logger.log_trade(
            market_id=opportunity.market_id,
            question=opportunity.question,
            token_id=yes_token_id,
            outcome="Yes",
            side="BUY",
            entry_price=opportunity.yes_price,
            quantity=calc['yes_quantity'],
            entry_value=calc['yes_cost'],
            ai_prediction=0,
            market_price_at_entry=opportunity.yes_price,
            balance_after=self.portfolio.cash_balance - calc['yes_cost']
        )
        
        # Execute NO trade
        no_token_id = opportunity.token_ids[1] if len(opportunity.token_ids) > 1 else f"{opportunity.market_id}_no"
        no_trade_id = self.logger.log_trade(
            market_id=opportunity.market_id,
            question=opportunity.question,
            token_id=no_token_id,
            outcome="No",
            side="BUY",
            entry_price=opportunity.no_price,
            quantity=calc['no_quantity'],
            entry_value=calc['no_cost'],
            ai_prediction=0,
            market_price_at_entry=opportunity.no_price,
            balance_after=self.portfolio.cash_balance - calc['total_cost']
        )
        
        # Update portfolio
        self.portfolio.cash_balance -= calc['total_cost']
        self.portfolio.total_trades += 2
        
        # Create hedged position entries
        yes_position = Position(
            market_id=opportunity.market_id,
            token_id=yes_token_id,
            question=opportunity.question,
            outcome="Yes",
            side="BUY",
            entry_price=opportunity.yes_price,
            quantity=calc['yes_quantity'],
            entry_value=calc['yes_cost'],
            entry_time=str(json.dumps({"type": "arbitrage"})),
            trade_id=yes_trade_id,
            current_price=opportunity.yes_price,
            current_value=calc['yes_cost']
        )
        
        no_position = Position(
            market_id=opportunity.market_id,
            token_id=no_token_id,
            question=opportunity.question,
            outcome="No",
            side="BUY",
            entry_price=opportunity.no_price,
            quantity=calc['no_quantity'],
            entry_value=calc['no_cost'],
            entry_time=str(json.dumps({"type": "arbitrage"})),
            trade_id=no_trade_id,
            current_price=opportunity.no_price,
            current_value=calc['no_cost']
        )
        
        self.portfolio.positions[yes_token_id] = yes_position
        self.portfolio.positions[no_token_id] = no_position
        
        # Log portfolio snapshot
        summary = self.portfolio.get_portfolio_summary()
        self.logger.log_portfolio_snapshot(
            total_value=summary['total_value'],
            cash_balance=summary['cash_balance'],
            positions_value=summary['positions_value'],
            num_open_positions=summary['num_open_positions'],
            total_pnl=summary['total_pnl'],
            total_return_pct=summary['total_return_pct']
        )
        
        self._save_portfolio_state()
        
        print(f"\n   ✅ Bought {calc['yes_quantity']:.2f} YES @ ${opportunity.yes_price:.4f} = ${calc['yes_cost']:.2f}")
        print(f"   ✅ Bought {calc['no_quantity']:.2f} NO @ ${opportunity.no_price:.4f} = ${calc['no_cost']:.2f}")
        print(f"   💰 Guaranteed profit: ${calc['guaranteed_profit']:.2f} ({calc['profit_pct']:.2f}%)")
        print(f"   💵 New balance: ${self.portfolio.cash_balance:.2f}")
        
        result['success'] = True
        result['trades'] = [
            {'side': 'YES', 'qty': calc['yes_quantity'], 'cost': calc['yes_cost']},
            {'side': 'NO', 'qty': calc['no_quantity'], 'cost': calc['no_cost']}
        ]
        result['guaranteed_profit'] = calc['guaranteed_profit']
        result['profit_pct'] = calc['profit_pct']
        
        return result

    def execute_arbitrage_cycle(
        self, 
        max_trades: int = 3,
        min_edge_pct: float = 0.5,
        budget_pct_per_trade: float = 0.1
    ) -> Dict[str, Any]:
        """Execute multiple arbitrage trades."""
        
        print("\n" + "="*60)
        print("  ARBITRAGE TRADING CYCLE")
        print("="*60)
        
        results = {
            'trades_executed': 0,
            'total_invested': 0,
            'guaranteed_profit': 0,
            'opportunities_found': 0,
            'details': []
        }
        
        # Scan for opportunities
        print("\n🔍 Scanning for arbitrage opportunities...")
        opportunities = self.scan_arbitrage_opportunities(
            min_edge_pct=min_edge_pct,
            min_liquidity=100,
            limit=max_trades * 2
        )
        
        results['opportunities_found'] = len(opportunities)
        print(f"   Found {len(opportunities)} opportunities with edge >= {min_edge_pct}%")
        
        if not opportunities:
            print("   No arbitrage opportunities found.")
            return results
        
        # Execute trades
        for opp in opportunities[:max_trades]:
            if self.portfolio.cash_balance < 50:
                print(f"\n⚠️  Low cash (${self.portfolio.cash_balance:.2f}), stopping.")
                break
            
            trade_result = self.execute_arbitrage_trade(opp, budget_pct_per_trade)
            
            if trade_result['success']:
                results['trades_executed'] += 1
                results['total_invested'] += trade_result.get('trades', [{}])[0].get('cost', 0) * 2
                results['guaranteed_profit'] += trade_result.get('guaranteed_profit', 0)
                results['details'].append(trade_result)
        
        # Summary
        print("\n" + "="*60)
        print("  ARBITRAGE CYCLE COMPLETE")
        print("="*60)
        print(f"  Trades executed: {results['trades_executed']}")
        print(f"  Total invested: ${results['total_invested']:.2f}")
        print(f"  Guaranteed profit: ${results['guaranteed_profit']:.2f}")
        summary = self.portfolio.get_portfolio_summary()
        print(f"  Portfolio value: ${summary['total_value']:.2f}")
        print("="*60)
        
        return results

    # ==================== GABAGOOL STRATEGY ====================
    
    def execute_gabagool_cycle(
        self,
        max_trades: int = 3,
        min_edge_pct: float = 0.5,
        budget_per_trade: float = 50.0
    ) -> Dict[str, Any]:
        """
        Execute the Gabagool strategy: buy both sides when cheap.
        
        No AI predictions. Pure math.
        """
        print("\n" + "="*60)
        print("  GABAGOOL TRADING CYCLE")
        print("="*60)
        print("  Strategy: Buy both YES and NO when total < $1.00")
        print("  No predictions. Just math.")
        print("="*60)
        
        results = {
            'trades_executed': 0,
            'opportunities_found': 0,
            'total_invested': 0.0,
            'guaranteed_profit': 0.0,
            'details': []
        }
        
        # Find opportunities
        print("\n🔍 Scanning for opportunities...")
        opportunities = self.gabagool.get_all_markets_with_edge(min_edge_pct=min_edge_pct)
        results['opportunities_found'] = len(opportunities)
        
        if not opportunities:
            print("   No opportunities found (market is efficient)")
            return results
        
        print(f"   Found {len(opportunities)} opportunities\n")
        
        # Execute trades
        for opp in opportunities[:max_trades]:
            if self.portfolio.cash_balance < budget_per_trade:
                print(f"⚠️  Low cash (${self.portfolio.cash_balance:.2f}), stopping.")
                break
            
            print(f"📊 {opp['question'][:50]}...")
            print(f"   YES: ${opp['yes_price']:.4f} | NO: ${opp['no_price']:.4f} | Edge: {opp['edge_pct']:.2f}%")
            
            # Execute gabagool trade
            trade_result = self.gabagool.execute_gabagool_trade(opp, budget_per_trade)
            
            # Update portfolio cash (simulated)
            self.portfolio.cash_balance -= budget_per_trade
            self.portfolio.total_trades += 2
            self._save_portfolio_state()
            
            results['trades_executed'] += 1
            results['total_invested'] += budget_per_trade
            
            pos = trade_result['position']
            if pos['is_profit_locked']:
                results['guaranteed_profit'] += pos['guaranteed_profit']
                print(f"   ✅ PROFIT LOCKED: ${pos['guaranteed_profit']:.2f}")
            else:
                print(f"   ⏳ Position building... pair cost: ${pos['pair_cost']:.4f}")
            
            results['details'].append(trade_result)
        
        # Summary
        print("\n" + "="*60)
        print("  GABAGOOL CYCLE COMPLETE")
        print("="*60)
        
        gab_summary = self.gabagool.get_summary()
        print(f"  Trades executed: {results['trades_executed']}")
        print(f"  Total invested: ${results['total_invested']:.2f}")
        print(f"  Locked positions: {gab_summary['locked_positions']}/{gab_summary['total_positions']}")
        print(f"  Guaranteed profit: ${gab_summary['total_guaranteed_profit']:.2f}")
        
        summary = self.portfolio.get_portfolio_summary()
        print(f"  Portfolio cash: ${summary['cash_balance']:.2f}")
        print("="*60)
        
        return results
    
    def get_gabagool_positions(self) -> List[Dict]:
        """Get all gabagool positions."""
        return self.gabagool.get_all_positions()
    
    def get_gabagool_summary(self) -> Dict:
        """Get gabagool strategy summary."""
        return self.gabagool.get_summary()
    
    def watch_markets(self, duration: float = None):
        """Watch markets for opportunities."""
        def on_opportunity(opp):
            # Auto-execute on arbitrage opportunities
            if opp.get('type') == 'ARBITRAGE' and opp.get('edge_pct', 0) > 1.0:
                print(f"\n🚀 Auto-executing on {opp['edge_pct']:.2f}% edge...")
                # Could auto-execute here
        
        self.watcher.add_callback(on_opportunity)
        self.watcher.watch(duration=duration)

    # ==================== MARKET MAKING ====================

    def run_market_making(
        self,
        token_ids: List[str],
        duration_seconds: float = 900,
        poll_interval: float = 1.0,
        config: MarketMakerConfig = None,
    ) -> Dict[str, Any]:
        """Run market making loop using WebSocket updates."""
        mm_config = config or MarketMakerConfig()
        market_maker = MarketMaker(
            portfolio=self.portfolio,
            spread_model=PolymarketSpreadModel(),
            config=mm_config,
        )

        self.market_tracker.start_websocket_feed(token_ids)

        results = {
            'orders_generated': 0,
            'orders_executed': 0,
            'start_time': datetime.utcnow().isoformat(),
        }
        last_processed_ts: Dict[str, Any] = {}

        try:
            start = time.monotonic()
            while time.monotonic() - start < duration_seconds:
                print(f"[PaperTrader] Checking {len(token_ids)} tokens...")
                for token_id in token_ids:
                    update = self.market_tracker.get_websocket_update(token_id, max_age_seconds=5)
                    print(f"[PaperTrader] Got update for {token_id}: {update is not None}")
                    if not update:
                        continue

                    update_ts = _extract_ws_timestamp(update)
                    if update_ts is not None and last_processed_ts.get(token_id) == update_ts:
                        continue
                    if update_ts is not None:
                        last_processed_ts[token_id] = update_ts

                    market_data = _build_market_data_from_ws(token_id, update)
                    if not market_data:
                        print(f"[PaperTrader] No market data built for {token_id}")
                        continue

                    mid_price = market_data.get("mid_price")
                    if mid_price:
                        self.portfolio.update_position_prices({token_id: mid_price})

                    orders = market_maker.on_market_update(market_data)
                    if not orders:
                        print(f"[PaperTrader] No orders for {token_id}")
                        continue

                    results['orders_generated'] += len(orders)
                    for order in orders:
                        if self._execute_market_maker_order(order, market_data):
                            results['orders_executed'] += 1
                            print(f"[PaperTrader] Executed {order.side} for {token_id}")

                time.sleep(poll_interval)
        finally:
            self.market_tracker.stop_websocket_feed()

        summary = self.portfolio.get_portfolio_summary()
        self.logger.log_portfolio_snapshot(
            total_value=summary['total_value'],
            cash_balance=summary['cash_balance'],
            positions_value=summary['positions_value'],
            num_open_positions=summary['num_open_positions'],
            total_pnl=summary['total_pnl'],
            total_return_pct=summary['total_return_pct'],
        )
        results['end_time'] = datetime.utcnow().isoformat()
        results['portfolio_value'] = summary['total_value']
        return results

    def _execute_market_maker_order(
        self,
        order: QuoteOrder,
        market_data: Dict[str, Any],
    ) -> bool:
        """Execute a market making order in paper mode."""
        if order.side not in {"BUY", "SELL"}:
            return False

        market_id = order.market_id
        token_id = order.token_id
        question = market_data.get("question", "")
        outcome = market_data.get("outcome", "YES")

        mid_price = market_data.get("mid_price") or order.price
        if mid_price is None:
            return False

        spread_abs = market_data.get("spread")
        spread_pct = None
        if spread_abs is not None and mid_price:
            try:
                spread_abs = float(spread_abs)
            except (TypeError, ValueError):
                spread_abs = None
        if spread_abs is None:
            liquidity = float(market_data.get("liquidity") or 0)
            volume_24h = float(market_data.get("volume_24h") or market_data.get("volume") or 0)
            spread_model = PolymarketSpreadModel()
            spread_pct = spread_model.calculate_spread(
                liquidity=liquidity,
                volume_24h=volume_24h,
                order_size=order.notional,
                price=mid_price,
            )
            spread_abs = mid_price * spread_pct
        elif mid_price:
            spread_pct = spread_abs / mid_price if mid_price > 0 else 0.0

        half_spread = (spread_abs or 0.0) / 2
        bid_price = max(0.001, mid_price - half_spread)
        ask_price = min(0.999, mid_price + half_spread)
        if self.use_realistic_fills:
            execution_price = ask_price if order.side == "BUY" else bid_price
        else:
            execution_price = bid_price if order.side == "BUY" else ask_price

        if order.side == "BUY":
            if self.portfolio.cash_balance <= 0:
                return False
            size_pct = order.notional / max(self.portfolio.cash_balance, 1e-6)
        else:
            position = self.portfolio.positions.get(token_id)
            if not position:
                return False
            position_value = position.current_value or position.entry_value
            if position_value <= 0:
                return False
            size_pct = order.notional / max(position_value, 1e-6)

        size_pct = max(0.0, min(size_pct, 1.0))
        if size_pct <= 0:
            return False

        trade_id = self.logger.log_trade(
            market_id=market_id,
            question=question,
            token_id=token_id,
            outcome=outcome,
            side=order.side,
            entry_price=execution_price,
            quantity=0,
            entry_value=0,
            ai_prediction=0,
            market_price_at_entry=mid_price,
            balance_after=self.portfolio.cash_balance,
        )

        market_conditions = None
        if self.use_realistic_fills:
            try:
                from agents.application.fill_simulator import MarketConditions

                liquidity = float(market_data.get("liquidity") or 0)
                volume_24h = float(market_data.get("volume_24h") or market_data.get("volume") or 0)
                if spread_pct is None:
                    spread_pct = spread_abs / mid_price if mid_price else 0.0
                market_conditions = MarketConditions(
                    mid_price=mid_price,
                    bid_price=bid_price,
                    ask_price=ask_price,
                    spread=spread_pct or 0.0,
                    liquidity=liquidity,
                    volume_24h=volume_24h,
                )
            except Exception:
                market_conditions = None

        position, execution_result = self.portfolio.execute_simulated_trade(
            market_id=market_id,
            token_id=token_id,
            question=question,
            outcome=outcome,
            side=order.side,
            price=execution_price,
            size_pct=size_pct,
            trade_id=trade_id,
            market_conditions=market_conditions,
            liquidity=float(market_data.get("liquidity") or 0),
            volume_24h=float(market_data.get("volume_24h") or market_data.get("volume") or 0),
        )

        if not position:
            return False

        from agents.application.trade_logger import sqlite3
        conn = sqlite3.connect(self.logger.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE trades
            SET quantity = ?, entry_value = ?, entry_price = ?, balance_after = ?
            WHERE id = ?
        ''', (
            position.quantity,
            position.entry_value,
            position.entry_price,
            self.portfolio.cash_balance,
            trade_id
        ))
        conn.commit()
        conn.close()

        return True


if __name__ == "__main__":
    trader = PaperTrader()
    result = trader.execute_paper_trade_cycle()
    print(f"\nResult: {result}")


def _build_market_data_from_ws(token_id: str, update: Any) -> Optional[Dict[str, Any]]:
    if not update:
        return None

    normalized = _normalize_ws_update(update, token_id=token_id)
    if not normalized:
        _debug_ws_payload(token_id, update)
        return None

    market_id = normalized.get("market") or normalized.get("asset_id") or normalized.get("assetId")

    mid_price = _extract_ws_mid_price(update, token_id=token_id)
    if mid_price is None:
        _debug_ws_payload(token_id, update)
        return None

    liquidity = _extract_ws_liquidity(normalized)
    spread = _extract_ws_spread(normalized, token_id=token_id)

    parsed_timestamp = _parse_ws_timestamp(normalized.get("timestamp"))
    return {
        "market_id": str(market_id) if market_id is not None else str(token_id),
        "token_id": str(token_id),
        "mid_price": mid_price,
        "price": mid_price,
        "spread": spread,
        "timestamp": parsed_timestamp,
        "liquidity": liquidity,
        "volume": normalized.get("volume"),
        "volume_24h": normalized.get("volume_24h"),
    }


def _extract_ws_mid_price(update: Any, token_id: Optional[str] = None) -> Optional[float]:
    normalized = _normalize_ws_update(update, token_id=token_id)
    if not normalized:
        return None

    event_type = normalized.get("event_type") or normalized.get("eventType")

    if event_type == "price_change":
        best_bid, best_ask = _best_bid_ask_from_price_change(normalized, token_id=token_id)
        if best_bid is not None and best_ask is not None and best_bid > 0 and best_ask > 0:
            return (best_bid + best_ask) / 2
    elif event_type == "book":
        bids = normalized.get("bids") or []
        asks = normalized.get("asks") or []
        best_bid = float(bids[0]["price"]) if bids else None
        best_ask = float(asks[0]["price"]) if asks else None
        if best_bid is not None and best_ask is not None:
            return (best_bid + best_ask) / 2
        if best_bid is not None:
            return best_bid
        if best_ask is not None:
            return best_ask
        last_trade = normalized.get("last_trade_price")
        if last_trade:
            return float(last_trade)
    elif event_type == "last_trade_price":
        price = normalized.get("price")
        if price:
            return float(price)
    elif event_type == "best_bid_ask":
        best_bid = normalized.get("best_bid")
        best_ask = normalized.get("best_ask")
        if best_bid and best_ask:
            return (float(best_bid) + float(best_ask)) / 2

    if "price" in normalized:
        try:
            return float(normalized["price"])
        except (TypeError, ValueError):
            return None

    return None


def _extract_ws_timestamp(update: Any) -> Optional[Any]:
    normalized = _normalize_ws_update(update)
    if isinstance(normalized, dict):
        return normalized.get("timestamp")
    return None


_WS_DEBUGGED_TOKENS = set()


def _debug_ws_payload(token_id: str, update: Any) -> None:
    if token_id in _WS_DEBUGGED_TOKENS:
        return
    _WS_DEBUGGED_TOKENS.add(token_id)
    if isinstance(update, list):
        preview = update[0] if update else None
        print(f"[PaperTrader] WS payload for {token_id} is list preview={preview}")
        return
    if not isinstance(update, dict):
        print(f"[PaperTrader] WS payload for {token_id} is {type(update)}")
        return
    event_type = update.get("event_type") or update.get("eventType")
    price_changes = update.get("price_changes") or update.get("priceChanges")
    preview = None
    if isinstance(price_changes, list) and price_changes:
        preview = price_changes[0]
    print(
        "[PaperTrader] WS payload missing price for {}: event_type={} keys={} price_changes_preview={}".format(
            token_id,
            event_type,
            list(update.keys()),
            preview,
        )
    )


def _normalize_ws_update(update: Any, token_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    if isinstance(update, dict):
        return update
    if isinstance(update, list):
        if token_id is not None:
            for item in update:
                if isinstance(item, dict):
                    asset_id = item.get("asset_id") or item.get("assetId")
                    if asset_id and str(asset_id) == str(token_id):
                        return item
        for item in update:
            if isinstance(item, dict):
                return item
    return None


def _parse_ws_timestamp(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        if isinstance(value, (int, float)):
            timestamp = float(value)
        else:
            timestamp = float(str(value))
    except (TypeError, ValueError):
        return None

    if timestamp > 1e12:
        timestamp /= 1000.0
    return datetime.utcfromtimestamp(timestamp)


def _best_bid_ask_from_price_change(
    normalized: Dict[str, Any],
    token_id: Optional[str] = None,
) -> Tuple[Optional[float], Optional[float]]:
    price_changes = normalized.get("price_changes") or normalized.get("priceChanges") or []
    if not isinstance(price_changes, list) or not price_changes:
        return None, None

    match = None
    if token_id is not None:
        for change in price_changes:
            if isinstance(change, dict):
                asset_id = change.get("asset_id") or change.get("assetId")
                if asset_id and str(asset_id) == str(token_id):
                    match = change
                    break

    if match is None:
        match = price_changes[0] if isinstance(price_changes[0], dict) else None

    if not match:
        return None, None

    best_bid = match.get("best_bid")
    best_ask = match.get("best_ask")
    try:
        return float(best_bid) if best_bid is not None else None, float(best_ask) if best_ask is not None else None
    except (TypeError, ValueError):
        return None, None


def _extract_ws_liquidity(normalized: Dict[str, Any]) -> float:
    if (normalized.get("event_type") or normalized.get("eventType")) == "book":
        bids = normalized.get("bids") or []
        asks = normalized.get("asks") or []
        bid_liq = sum(float(b["size"]) for b in bids[:5]) if bids else 0.0
        ask_liq = sum(float(a["size"]) for a in asks[:5]) if asks else 0.0
        return bid_liq + ask_liq
    return 0.0


def _extract_ws_spread(normalized: Dict[str, Any], token_id: Optional[str] = None) -> Optional[float]:
    event_type = normalized.get("event_type") or normalized.get("eventType")
    if event_type == "best_bid_ask":
        spread = normalized.get("spread")
        return float(spread) if spread is not None else None
    if event_type == "price_change":
        best_bid, best_ask = _best_bid_ask_from_price_change(normalized, token_id=token_id)
        if best_bid is not None and best_ask is not None:
            return best_ask - best_bid
    if event_type == "book":
        bids = normalized.get("bids") or []
        asks = normalized.get("asks") or []
        if bids and asks:
            return float(asks[0]["price"]) - float(bids[0]["price"])
    return None
