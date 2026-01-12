"""
Bot Control API Router
"""

from fastapi import APIRouter, HTTPException
from typing import List, Dict, Any

from services import trading_service
from state import bot_state
from schemas import StatusResponse, StartBotRequest, BotStatus, PortfolioSummary

router = APIRouter(prefix="/bot", tags=["bot"])


@router.get("/status", response_model=StatusResponse)
async def get_status():
    """Get bot status and portfolio summary."""
    try:
        summary = trading_service.get_portfolio_summary()
        return StatusResponse(
            bot_status=bot_state.status,
            mode="paper",
            portfolio=PortfolioSummary(**summary),
            active_strategies=bot_state.get_enabled_strategies(),
            uptime_seconds=bot_state.uptime_seconds
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/start")
async def start_bot(request: StartBotRequest) -> Dict[str, Any]:
    """Start the trading bot with a preset."""
    try:
        success = bot_state.start(preset=request.preset)
        return {
            "success": success,
            "status": bot_state.status.value,
            "preset": request.preset,
            "message": "Bot started" if success else "Bot was already running"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stop")
async def stop_bot() -> Dict[str, Any]:
    """Stop the trading bot."""
    try:
        success = bot_state.stop()
        return {
            "success": success,
            "status": bot_state.status.value,
            "message": "Bot stopped" if success else "Bot was already stopped"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/activity")
async def get_activity(limit: int = 50) -> List[Dict[str, str]]:
    """Get recent activity log entries."""
    try:
        return bot_state.get_activity_log(limit=limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
