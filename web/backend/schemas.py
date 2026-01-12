"""
Pydantic schemas for Kink-Hunter Pro API
"""

from pydantic import BaseModel
from typing import List, Optional, Dict
from enum import Enum


class BotStatus(str, Enum):
    STOPPED = "stopped"
    RUNNING = "running"
    SCANNING = "scanning"


class StrategyType(str, Enum):
    FULLSET = "fullset"
    ENDGAME = "endgame"
    ORACLE = "oracle"
    REWARDS = "rewards"


class PortfolioSummary(BaseModel):
    total_value: float
    cash_balance: float
    positions_value: float
    total_pnl: float
    total_return_pct: float
    realized_pnl: float
    unrealized_pnl: float
    num_open_positions: int
    total_trades: int


class Position(BaseModel):
    market_id: str
    token_id: str
    question: str
    outcome: str
    side: str
    entry_price: float
    quantity: float
    entry_value: float
    current_price: float
    current_value: float
    unrealized_pnl: float


class Opportunity(BaseModel):
    id: str
    name: str
    strategy: str
    edge: float
    edge_pct: float
    annualized_return: Optional[float] = None
    liquidity: float
    days_until_resolution: Optional[float] = None
    total_cost: Optional[float] = None
    num_outcomes: Optional[int] = None


class ActivityLogEntry(BaseModel):
    timestamp: str
    type: str  # "scan", "trade", "info", "error"
    message: str


class BotSettings(BaseModel):
    risk_appetite: float = 0.5  # 0.0 - 1.0
    strategies_enabled: Dict[str, bool] = {
        "fullset": True,
        "endgame": True,
        "oracle": False,
        "rewards": True,
    }
    max_capital: float = 1000.0


class StatusResponse(BaseModel):
    bot_status: BotStatus
    mode: str = "paper"
    portfolio: PortfolioSummary
    active_strategies: List[str]
    uptime_seconds: float = 0


class StartBotRequest(BaseModel):
    preset: str = "balanced"  # "safe", "balanced", "aggressive"


class SettingsUpdateRequest(BaseModel):
    risk_appetite: Optional[float] = None
    strategies_enabled: Optional[Dict[str, bool]] = None
    max_capital: Optional[float] = None


# Preset configurations
STRATEGY_PRESETS = {
    "safe": {
        "risk_appetite": 0.25,
        "strategies_enabled": {
            "fullset": False,
            "endgame": True,
            "oracle": False,
            "rewards": True,
        },
        "min_edge": 2.0,
        "max_days": 30,
        "capital_pct": 0.10,
    },
    "balanced": {
        "risk_appetite": 0.50,
        "strategies_enabled": {
            "fullset": True,
            "endgame": True,
            "oracle": False,
            "rewards": True,
        },
        "min_edge": 1.0,
        "max_days": 90,
        "capital_pct": 0.25,
    },
    "aggressive": {
        "risk_appetite": 0.75,
        "strategies_enabled": {
            "fullset": True,
            "endgame": True,
            "oracle": True,
            "rewards": False,
        },
        "min_edge": 0.5,
        "max_days": 365,
        "capital_pct": 0.50,
    },
}
