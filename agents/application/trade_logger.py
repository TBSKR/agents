import sqlite3
import csv
import json
import os
from datetime import datetime
from typing import Optional, List, Dict, Any
from pathlib import Path


class TradeLogger:
    def __init__(self, db_path: str = None):
        if db_path is None:
            base_dir = Path(__file__).parent.parent.parent
            self.data_dir = base_dir / "data"
            self.exports_dir = self.data_dir / "exports"
            self.backups_dir = self.data_dir / "backups"
            db_path = str(self.data_dir / "paper_trading.db")
        else:
            self.data_dir = Path(db_path).parent
            self.exports_dir = self.data_dir / "exports"
            self.backups_dir = self.data_dir / "backups"
        
        self.db_path = db_path
        self._ensure_directories()
        self._init_database()

    def _ensure_directories(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.exports_dir.mkdir(parents=True, exist_ok=True)
        self.backups_dir.mkdir(parents=True, exist_ok=True)

    def _init_database(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                market_id TEXT NOT NULL,
                question TEXT,
                token_id TEXT,
                outcome TEXT,
                side TEXT NOT NULL,
                entry_price REAL NOT NULL,
                quantity REAL NOT NULL,
                entry_value REAL NOT NULL,
                exit_price REAL,
                exit_time TEXT,
                realized_pnl REAL,
                status TEXT DEFAULT 'open',
                ai_prediction REAL,
                market_price_at_entry REAL,
                balance_after REAL
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS portfolio_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                total_value REAL NOT NULL,
                cash_balance REAL NOT NULL,
                positions_value REAL NOT NULL,
                num_open_positions INTEGER NOT NULL,
                total_pnl REAL NOT NULL,
                total_return_pct REAL NOT NULL
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS market_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                trade_id INTEGER,
                market_id TEXT NOT NULL,
                question TEXT,
                outcomes TEXT,
                outcome_prices TEXT,
                volume REAL,
                liquidity REAL,
                spread REAL,
                FOREIGN KEY (trade_id) REFERENCES trades(id)
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS ai_predictions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                trade_id INTEGER,
                market_id TEXT NOT NULL,
                question TEXT,
                outcome TEXT,
                predicted_probability REAL,
                market_probability REAL,
                edge REAL,
                reasoning TEXT,
                actual_outcome TEXT,
                prediction_correct INTEGER,
                brier_score REAL,
                FOREIGN KEY (trade_id) REFERENCES trades(id)
            )
        ''')

        conn.commit()
        conn.close()

    def log_trade(
        self,
        market_id: str,
        question: str,
        token_id: str,
        outcome: str,
        side: str,
        entry_price: float,
        quantity: float,
        entry_value: float,
        ai_prediction: float,
        market_price_at_entry: float,
        balance_after: float
    ) -> int:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        timestamp = datetime.now().isoformat()
        
        cursor.execute('''
            INSERT INTO trades (
                timestamp, market_id, question, token_id, outcome, side,
                entry_price, quantity, entry_value, ai_prediction,
                market_price_at_entry, balance_after, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open')
        ''', (
            timestamp, market_id, question, token_id, outcome, side,
            entry_price, quantity, entry_value, ai_prediction,
            market_price_at_entry, balance_after
        ))
        
        trade_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        return trade_id

    def close_trade(
        self,
        trade_id: int,
        exit_price: float,
        realized_pnl: float
    ):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE trades
            SET exit_price = ?, exit_time = ?, realized_pnl = ?, status = 'closed'
            WHERE id = ?
        ''', (exit_price, datetime.now().isoformat(), realized_pnl, trade_id))
        
        conn.commit()
        conn.close()

    def log_portfolio_snapshot(
        self,
        total_value: float,
        cash_balance: float,
        positions_value: float,
        num_open_positions: int,
        total_pnl: float,
        total_return_pct: float
    ) -> int:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO portfolio_snapshots (
                timestamp, total_value, cash_balance, positions_value,
                num_open_positions, total_pnl, total_return_pct
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            datetime.now().isoformat(), total_value, cash_balance,
            positions_value, num_open_positions, total_pnl, total_return_pct
        ))
        
        snapshot_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        return snapshot_id

    def log_market_snapshot(
        self,
        trade_id: int,
        market_id: str,
        question: str,
        outcomes: str,
        outcome_prices: str,
        volume: float = None,
        liquidity: float = None,
        spread: float = None
    ) -> int:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO market_snapshots (
                timestamp, trade_id, market_id, question, outcomes,
                outcome_prices, volume, liquidity, spread
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            datetime.now().isoformat(), trade_id, market_id, question,
            outcomes, outcome_prices, volume, liquidity, spread
        ))
        
        snapshot_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        return snapshot_id

    def log_ai_prediction(
        self,
        trade_id: int,
        market_id: str,
        question: str,
        outcome: str,
        predicted_probability: float,
        market_probability: float,
        edge: float,
        reasoning: str = None
    ) -> int:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO ai_predictions (
                timestamp, trade_id, market_id, question, outcome,
                predicted_probability, market_probability, edge, reasoning
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            datetime.now().isoformat(), trade_id, market_id, question,
            outcome, predicted_probability, market_probability, edge, reasoning
        ))
        
        prediction_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        return prediction_id

    def update_prediction_result(
        self,
        prediction_id: int,
        actual_outcome: str,
        prediction_correct: bool,
        brier_score: float
    ):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE ai_predictions
            SET actual_outcome = ?, prediction_correct = ?, brier_score = ?
            WHERE id = ?
        ''', (actual_outcome, int(prediction_correct), brier_score, prediction_id))
        
        conn.commit()
        conn.close()

    def get_open_trades(self) -> List[Dict[str, Any]]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM trades WHERE status = 'open'")
        rows = cursor.fetchall()
        
        conn.close()
        return [dict(row) for row in rows]

    def get_all_trades(self) -> List[Dict[str, Any]]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM trades ORDER BY timestamp DESC")
        rows = cursor.fetchall()
        
        conn.close()
        return [dict(row) for row in rows]

    def get_latest_snapshot(self) -> Optional[Dict[str, Any]]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute(
            "SELECT * FROM portfolio_snapshots ORDER BY timestamp DESC LIMIT 1"
        )
        row = cursor.fetchone()
        
        conn.close()
        return dict(row) if row else None

    def get_all_predictions(self) -> List[Dict[str, Any]]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM ai_predictions ORDER BY timestamp DESC")
        rows = cursor.fetchall()
        
        conn.close()
        return [dict(row) for row in rows]

    def export_to_csv(self) -> Dict[str, str]:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        exported_files = {}
        
        tables = ['trades', 'portfolio_snapshots', 'market_snapshots', 'ai_predictions']
        
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        for table in tables:
            cursor.execute(f"SELECT * FROM {table}")
            rows = cursor.fetchall()
            
            if rows:
                filepath = self.exports_dir / f"{table}_{timestamp}.csv"
                with open(filepath, 'w', newline='') as f:
                    writer = csv.DictWriter(f, fieldnames=rows[0].keys())
                    writer.writeheader()
                    for row in rows:
                        writer.writerow(dict(row))
                exported_files[table] = str(filepath)
        
        conn.close()
        return exported_files

    def backup_to_json(self) -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        backup_data = {
            'trades': self.get_all_trades(),
            'portfolio_snapshots': self._get_all_snapshots(),
            'market_snapshots': self._get_all_market_snapshots(),
            'ai_predictions': self.get_all_predictions(),
            'backup_timestamp': datetime.now().isoformat()
        }
        
        filepath = self.backups_dir / f"backup_{timestamp}.json"
        with open(filepath, 'w') as f:
            json.dump(backup_data, f, indent=2, default=str)
        
        return str(filepath)

    def _get_all_snapshots(self) -> List[Dict[str, Any]]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM portfolio_snapshots ORDER BY timestamp DESC")
        rows = cursor.fetchall()
        
        conn.close()
        return [dict(row) for row in rows]

    def _get_all_market_snapshots(self) -> List[Dict[str, Any]]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM market_snapshots ORDER BY timestamp DESC")
        rows = cursor.fetchall()
        
        conn.close()
        return [dict(row) for row in rows]
