"""
Historical Data Collector - Collects and stores market data for backtesting.

This module provides:
- Market snapshot collection
- Price history storage
- Continuous data collection
- Data export for backtesting
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Any
import json
import sqlite3
import threading
import time


@dataclass
class MarketSnapshot:
    """Point-in-time snapshot of a market."""
    market_id: str
    token_id: str
    question: str
    outcome: str
    timestamp: datetime
    price: float
    volume_24h: float
    liquidity: float
    spread: float
    yes_price: float
    no_price: float

    def to_dict(self) -> dict:
        return {
            'market_id': self.market_id,
            'token_id': self.token_id,
            'question': self.question,
            'outcome': self.outcome,
            'timestamp': self.timestamp.isoformat(),
            'price': self.price,
            'volume_24h': self.volume_24h,
            'liquidity': self.liquidity,
            'spread': self.spread,
            'yes_price': self.yes_price,
            'no_price': self.no_price
        }


@dataclass
class PricePoint:
    """Single price observation."""
    timestamp: datetime
    price: float
    volume: float = 0
    liquidity: float = 0


class HistoricalDataCollector:
    """
    Collects and stores historical market data for backtesting.

    Features:
    - SQLite-based storage
    - Periodic snapshot collection
    - Price history queries
    - Data export
    """

    DEFAULT_DB_PATH = "historical_data.db"

    def __init__(self, db_path: str = None):
        """
        Initialize the data collector.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = Path(db_path or self.DEFAULT_DB_PATH)
        self._init_database()
        self._gamma_client = None
        self._collection_thread = None
        self._stop_collection = False

    def _init_database(self):
        """Initialize the SQLite database schema."""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        # Market snapshots table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS market_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                market_id TEXT NOT NULL,
                token_id TEXT,
                question TEXT,
                outcome TEXT,
                timestamp DATETIME NOT NULL,
                price REAL,
                volume_24h REAL,
                liquidity REAL,
                spread REAL,
                yes_price REAL,
                no_price REAL,
                UNIQUE(market_id, timestamp)
            )
        ''')

        # Price history table (for efficient time-series queries)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS price_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                market_id TEXT NOT NULL,
                timestamp DATETIME NOT NULL,
                price REAL NOT NULL,
                volume REAL,
                liquidity REAL,
                UNIQUE(market_id, timestamp)
            )
        ''')

        # Create indexes
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_snapshots_market_time
            ON market_snapshots(market_id, timestamp)
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_price_market_time
            ON price_history(market_id, timestamp)
        ''')

        conn.commit()
        conn.close()

    @property
    def gamma_client(self):
        """Lazy load Gamma client."""
        if self._gamma_client is None:
            try:
                from agents.polymarket.gamma import GammaMarketClient
                self._gamma_client = GammaMarketClient()
            except ImportError:
                pass
        return self._gamma_client

    def collect_market_snapshot(self, markets: List[Dict] = None) -> int:
        """
        Capture current state of all active markets.

        Args:
            markets: Optional list of market data (if None, fetches from API)

        Returns:
            Number of snapshots collected
        """
        if markets is None:
            markets = self._fetch_active_markets()

        if not markets:
            return 0

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        timestamp = datetime.now()
        count = 0

        for market in markets:
            try:
                # Extract market data
                market_id = market.get('id') or market.get('condition_id', '')
                question = market.get('question', '')

                # Get prices
                yes_price = float(market.get('yes_bid', 0) or market.get('outcomePrices', [0.5, 0.5])[0])
                no_price = float(market.get('no_bid', 0) or (market.get('outcomePrices', [0.5, 0.5])[1] if len(market.get('outcomePrices', [])) > 1 else 0.5))

                # Calculate spread
                spread = abs(1 - yes_price - no_price) if yes_price and no_price else 0

                # Get volume and liquidity
                volume_24h = float(market.get('volume24hr', 0) or market.get('volume', 0) or 0)
                liquidity = float(market.get('liquidity', 0) or 0)

                # Insert snapshot
                cursor.execute('''
                    INSERT OR REPLACE INTO market_snapshots
                    (market_id, question, timestamp, price, volume_24h, liquidity, spread, yes_price, no_price)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    market_id, question, timestamp, yes_price,
                    volume_24h, liquidity, spread, yes_price, no_price
                ))

                # Also insert into price history
                cursor.execute('''
                    INSERT OR REPLACE INTO price_history
                    (market_id, timestamp, price, volume, liquidity)
                    VALUES (?, ?, ?, ?, ?)
                ''', (market_id, timestamp, yes_price, volume_24h, liquidity))

                count += 1

            except Exception as e:
                print(f"Error collecting snapshot for market: {e}")
                continue

        conn.commit()
        conn.close()

        return count

    def _fetch_active_markets(self, limit: int = 200) -> List[Dict]:
        """Fetch active markets from Gamma API."""
        if self.gamma_client is None:
            return []

        try:
            import httpx
            params = {"active": "true", "closed": "false", "limit": limit}
            response = httpx.get(
                self.gamma_client.gamma_markets_endpoint,
                params=params,
                timeout=30
            )
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            print(f"Error fetching markets: {e}")

        return []

    def get_price_history(
        self,
        market_id: str,
        lookback_days: int = 30,
        start_date: datetime = None,
        end_date: datetime = None
    ) -> List[PricePoint]:
        """
        Get historical prices for a market.

        Args:
            market_id: Market identifier
            lookback_days: Number of days to look back (if no dates specified)
            start_date: Start of date range
            end_date: End of date range

        Returns:
            List of PricePoint objects
        """
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        if start_date is None:
            start_date = datetime.now() - timedelta(days=lookback_days)
        if end_date is None:
            end_date = datetime.now()

        cursor.execute('''
            SELECT timestamp, price, volume, liquidity
            FROM price_history
            WHERE market_id = ? AND timestamp BETWEEN ? AND ?
            ORDER BY timestamp ASC
        ''', (market_id, start_date, end_date))

        rows = cursor.fetchall()
        conn.close()

        return [
            PricePoint(
                timestamp=datetime.fromisoformat(row[0]),
                price=row[1],
                volume=row[2] or 0,
                liquidity=row[3] or 0
            )
            for row in rows
        ]

    def get_market_snapshots(
        self,
        market_id: str = None,
        start_date: datetime = None,
        end_date: datetime = None,
        limit: int = 1000
    ) -> List[MarketSnapshot]:
        """
        Get market snapshots.

        Args:
            market_id: Optional market ID filter
            start_date: Start of date range
            end_date: End of date range
            limit: Maximum number of results

        Returns:
            List of MarketSnapshot objects
        """
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        query = "SELECT * FROM market_snapshots WHERE 1=1"
        params = []

        if market_id:
            query += " AND market_id = ?"
            params.append(market_id)
        if start_date:
            query += " AND timestamp >= ?"
            params.append(start_date)
        if end_date:
            query += " AND timestamp <= ?"
            params.append(end_date)

        query += f" ORDER BY timestamp DESC LIMIT {limit}"

        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()

        return [
            MarketSnapshot(
                market_id=row[1],
                token_id=row[2] or '',
                question=row[3] or '',
                outcome=row[4] or '',
                timestamp=datetime.fromisoformat(row[5]),
                price=row[6] or 0,
                volume_24h=row[7] or 0,
                liquidity=row[8] or 0,
                spread=row[9] or 0,
                yes_price=row[10] or 0,
                no_price=row[11] or 0
            )
            for row in rows
        ]

    def start_continuous_collection(
        self,
        interval_seconds: int = 300,
        callback: callable = None
    ):
        """
        Start background data collection.

        Args:
            interval_seconds: Time between collections (default 5 minutes)
            callback: Optional callback after each collection
        """
        if self._collection_thread and self._collection_thread.is_alive():
            print("Collection already running")
            return

        self._stop_collection = False

        def collection_loop():
            while not self._stop_collection:
                try:
                    count = self.collect_market_snapshot()
                    print(f"[{datetime.now()}] Collected {count} market snapshots")

                    if callback:
                        callback(count)

                except Exception as e:
                    print(f"Collection error: {e}")

                time.sleep(interval_seconds)

        self._collection_thread = threading.Thread(target=collection_loop, daemon=True)
        self._collection_thread.start()
        print(f"Started continuous collection every {interval_seconds} seconds")

    def stop_continuous_collection(self):
        """Stop background data collection."""
        self._stop_collection = True
        if self._collection_thread:
            self._collection_thread.join(timeout=5)
        print("Stopped continuous collection")

    def export_to_json(
        self,
        filepath: str,
        market_id: str = None,
        start_date: datetime = None,
        end_date: datetime = None
    ):
        """
        Export data to JSON file.

        Args:
            filepath: Output file path
            market_id: Optional market ID filter
            start_date: Start of date range
            end_date: End of date range
        """
        snapshots = self.get_market_snapshots(
            market_id=market_id,
            start_date=start_date,
            end_date=end_date,
            limit=100000
        )

        data = {
            'exported_at': datetime.now().isoformat(),
            'count': len(snapshots),
            'snapshots': [s.to_dict() for s in snapshots]
        }

        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)

        print(f"Exported {len(snapshots)} snapshots to {filepath}")

    def get_statistics(self) -> dict:
        """Get database statistics."""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        # Count snapshots
        cursor.execute("SELECT COUNT(*) FROM market_snapshots")
        snapshot_count = cursor.fetchone()[0]

        # Count unique markets
        cursor.execute("SELECT COUNT(DISTINCT market_id) FROM market_snapshots")
        market_count = cursor.fetchone()[0]

        # Date range
        cursor.execute("SELECT MIN(timestamp), MAX(timestamp) FROM market_snapshots")
        date_range = cursor.fetchone()

        # Price history count
        cursor.execute("SELECT COUNT(*) FROM price_history")
        price_count = cursor.fetchone()[0]

        conn.close()

        return {
            'total_snapshots': snapshot_count,
            'unique_markets': market_count,
            'earliest_snapshot': date_range[0],
            'latest_snapshot': date_range[1],
            'price_history_records': price_count,
            'database_path': str(self.db_path)
        }

    def get_markets_with_data(self) -> List[str]:
        """Get list of market IDs that have historical data."""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        cursor.execute("SELECT DISTINCT market_id FROM price_history ORDER BY market_id")
        rows = cursor.fetchall()

        conn.close()

        return [row[0] for row in rows]
