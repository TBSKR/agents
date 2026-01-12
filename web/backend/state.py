"""
Bot State Management - Tracks bot status and activity log
"""

import threading
import time
from datetime import datetime
from typing import List, Dict, Any, Optional
from collections import deque

from schemas import BotStatus, BotSettings, ActivityLogEntry, STRATEGY_PRESETS


class BotState:
    """
    Manages the bot's runtime state including:
    - Running status
    - Activity log
    - Settings
    - Background worker thread
    """

    _instance: Optional['BotState'] = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._initialized = True
        self._status = BotStatus.STOPPED
        self._settings = BotSettings()
        self._activity_log: deque = deque(maxlen=100)  # Keep last 100 entries
        self._start_time: Optional[float] = None
        self._worker_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # Add initial log entry
        self.log("info", "Kink-Hunter Pro initialized")

    @property
    def status(self) -> BotStatus:
        return self._status

    @property
    def settings(self) -> BotSettings:
        return self._settings

    @property
    def uptime_seconds(self) -> float:
        if self._start_time is None:
            return 0
        return time.time() - self._start_time

    @property
    def is_running(self) -> bool:
        return self._status == BotStatus.RUNNING

    def log(self, log_type: str, message: str):
        """Add an entry to the activity log."""
        entry = ActivityLogEntry(
            timestamp=datetime.now().strftime("%H:%M:%S"),
            type=log_type,
            message=message
        )
        self._activity_log.append(entry)

    def get_activity_log(self, limit: int = 50) -> List[Dict[str, str]]:
        """Get recent activity log entries."""
        entries = list(self._activity_log)[-limit:]
        return [{"timestamp": e.timestamp, "type": e.type, "message": e.message} for e in reversed(entries)]

    def update_settings(
        self,
        risk_appetite: Optional[float] = None,
        strategies_enabled: Optional[Dict[str, bool]] = None,
        max_capital: Optional[float] = None
    ):
        """Update bot settings."""
        if risk_appetite is not None:
            self._settings.risk_appetite = max(0.0, min(1.0, risk_appetite))
            self.log("info", f"Risk appetite updated to {self._settings.risk_appetite:.0%}")

        if strategies_enabled is not None:
            self._settings.strategies_enabled.update(strategies_enabled)
            enabled = [k for k, v in self._settings.strategies_enabled.items() if v]
            self.log("info", f"Active strategies: {', '.join(enabled)}")

        if max_capital is not None:
            self._settings.max_capital = max_capital
            self.log("info", f"Max capital set to ${max_capital:.2f}")

    def apply_preset(self, preset: str):
        """Apply a strategy preset."""
        if preset not in STRATEGY_PRESETS:
            self.log("error", f"Unknown preset: {preset}")
            return

        config = STRATEGY_PRESETS[preset]
        self._settings.risk_appetite = config["risk_appetite"]
        self._settings.strategies_enabled = config["strategies_enabled"].copy()

        self.log("info", f"Applied '{preset}' preset")
        enabled = [k for k, v in self._settings.strategies_enabled.items() if v]
        self.log("info", f"Strategies: {', '.join(enabled)}")

    def start(self, preset: str = "balanced"):
        """Start the trading bot."""
        if self._status == BotStatus.RUNNING:
            self.log("info", "Bot is already running")
            return False

        self.apply_preset(preset)
        self._status = BotStatus.RUNNING
        self._start_time = time.time()
        self._stop_event.clear()

        # Start background worker
        self._worker_thread = threading.Thread(target=self._run_worker, daemon=True)
        self._worker_thread.start()

        self.log("trade", "Bot started in paper trading mode")
        return True

    def stop(self):
        """Stop the trading bot."""
        if self._status == BotStatus.STOPPED:
            self.log("info", "Bot is already stopped")
            return False

        self._stop_event.set()
        self._status = BotStatus.STOPPED

        if self._worker_thread:
            self._worker_thread.join(timeout=5)
            self._worker_thread = None

        uptime = self.uptime_seconds
        self._start_time = None

        self.log("info", f"Bot stopped after {uptime:.0f}s")
        return True

    def _run_worker(self):
        """Background worker that scans for opportunities."""
        from services import trading_service

        scan_interval = 60  # Scan every 60 seconds
        last_scan = 0

        while not self._stop_event.is_set():
            current_time = time.time()

            # Scan for opportunities periodically
            if current_time - last_scan >= scan_interval:
                self._status = BotStatus.SCANNING
                self._scan_opportunities(trading_service)
                self._status = BotStatus.RUNNING
                last_scan = current_time

            # Sleep in small increments to allow quick stopping
            self._stop_event.wait(timeout=1)

    def _scan_opportunities(self, service):
        """Scan for opportunities based on enabled strategies."""
        settings = self._settings

        # Map risk appetite to parameters
        risk = settings.risk_appetite
        min_edge = 2.0 - (risk * 1.5)  # 2.0% at 0 risk, 0.5% at 100% risk
        max_days = int(30 + (risk * 335))  # 30 days at 0 risk, 365 at 100% risk

        total_found = 0

        if settings.strategies_enabled.get("fullset"):
            self.log("scan", "Scanning full-set arbitrage...")
            try:
                opps = service.scan_fullset_opportunities(
                    min_edge_pct=min_edge,
                    max_days=max_days,
                    limit=5
                )
                if opps:
                    best = opps[0]
                    self.log("scan", f"Found {len(opps)} fullset opportunities")
                    self.log("info", f"Best: {best['name'][:40]}... ({best['annualized_return']:.1f}% APY)")
                    total_found += len(opps)
            except Exception as e:
                self.log("error", f"Fullset scan error: {str(e)[:50]}")

        if settings.strategies_enabled.get("endgame"):
            self.log("scan", "Scanning endgame sweeps...")
            try:
                opps = service.scan_endgame_opportunities(
                    min_liquidity=500,
                    max_days=max_days,
                    limit=5
                )
                if opps:
                    best = opps[0]
                    self.log("scan", f"Found {len(opps)} endgame opportunities")
                    self.log("info", f"Best: {best['name'][:40]}... ({best['annualized_return']:.1f}% APY)")
                    total_found += len(opps)
            except Exception as e:
                self.log("error", f"Endgame scan error: {str(e)[:50]}")

        if settings.strategies_enabled.get("oracle"):
            self.log("scan", "Scanning oracle timing...")
            try:
                opps = service.scan_oracle_opportunities(min_edge_pct=1.0, limit=5)
                if opps:
                    self.log("scan", f"Found {len(opps)} oracle opportunities")
                    total_found += len(opps)
            except Exception as e:
                self.log("error", f"Oracle scan error: {str(e)[:50]}")

        if total_found == 0:
            self.log("info", "No opportunities found matching criteria")

    def get_enabled_strategies(self) -> List[str]:
        """Get list of enabled strategy names."""
        return [k for k, v in self._settings.strategies_enabled.items() if v]


# Global state instance
bot_state = BotState()
