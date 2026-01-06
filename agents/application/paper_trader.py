import re
import ast
import json
import shutil
from pathlib import Path
from typing import Optional, Tuple, Dict, Any, List

from agents.application.paper_portfolio import PaperPortfolio, Position
from agents.application.trade_logger import TradeLogger
from agents.application.market_tracker import MarketTracker
from agents.application.arbitrage_engine import ArbitrageEngine, ArbitrageOpportunity
from agents.application.gabagool_trader import GabagoolTrader
from agents.application.market_watcher import MarketWatcher
from agents.polymarket.gamma import GammaMarketClient


class PaperTrader:
    PORTFOLIO_STATE_FILE = "portfolio_state.json"

    def __init__(self, initial_balance: float = 1000.0):
        self._agent = None
        self._arbitrage_engine = None
        self._gabagool = None
        self._watcher = None
        
        self.gamma = GammaMarketClient()
        self.logger = TradeLogger()
        self.market_tracker = MarketTracker()
        
        state_path = self.logger.data_dir / self.PORTFOLIO_STATE_FILE
        if state_path.exists():
            self.portfolio = PaperPortfolio.load_state(str(state_path))
            print(f"Loaded existing portfolio: ${self.portfolio.get_total_value():.2f}")
        else:
            self.portfolio = PaperPortfolio(initial_balance=initial_balance)
            print(f"Created new portfolio with ${initial_balance:.2f}")

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
                result['size'] = float(size_match[0])
            
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
            print(f"   Price: {trade_params['price']}")
            print(f"   Size: {trade_params['size']*100:.1f}% of portfolio")

            trade_id = self.logger.log_trade(
                market_id=market_id,
                question=question,
                token_id=token_id,
                outcome=ai_outcome or outcomes[outcome_idx],
                side=trade_params['side'],
                entry_price=trade_params['price'],
                quantity=0,
                entry_value=0,
                ai_prediction=ai_prob or 0,
                market_price_at_entry=market_price,
                balance_after=self.portfolio.cash_balance
            )

            position = self.portfolio.execute_simulated_trade(
                market_id=market_id,
                token_id=token_id,
                question=question,
                outcome=ai_outcome or outcomes[outcome_idx],
                side=trade_params['side'],
                price=trade_params['price'],
                size_pct=trade_params['size'],
                trade_id=trade_id
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
            print(f"   New balance: ${self.portfolio.cash_balance:.2f}")
            print(f"   Total portfolio value: ${summary['total_value']:.2f}")
            print(f"   Total P&L: ${summary['total_pnl']:.2f} ({summary['total_return_pct']:+.2f}%)")

            result['success'] = True
            result['trade'] = {
                'trade_id': trade_id,
                'market_id': market_id,
                'question': question,
                'side': trade_params['side'],
                'price': trade_params['price'],
                'size_pct': trade_params['size'],
                'ai_prediction': ai_prob,
                'market_price': market_price,
                'edge': edge
            }
            result['position'] = position.to_dict() if position else None

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

        realized_pnl = self.portfolio.close_position(token_id, current_price)
        
        open_trades = self.logger.get_open_trades()
        for trade in open_trades:
            if trade['token_id'] == token_id:
                self.logger.close_trade(trade['id'], current_price, realized_pnl)
                break

        self._save_portfolio_state()

        return {
            'success': True,
            'realized_pnl': realized_pnl,
            'exit_price': current_price
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


if __name__ == "__main__":
    trader = PaperTrader()
    result = trader.execute_paper_trade_cycle()
    print(f"\nResult: {result}")
