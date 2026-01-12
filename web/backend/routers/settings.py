"""
Settings API Router
"""

from fastapi import APIRouter, HTTPException
from typing import Dict, Any

from state import bot_state
from schemas import BotSettings, SettingsUpdateRequest

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=BotSettings)
async def get_settings():
    """Get current bot settings."""
    return bot_state.settings


@router.post("")
async def update_settings(request: SettingsUpdateRequest) -> Dict[str, Any]:
    """Update bot settings."""
    try:
        bot_state.update_settings(
            risk_appetite=request.risk_appetite,
            strategies_enabled=request.strategies_enabled,
            max_capital=request.max_capital
        )
        return {
            "success": True,
            "settings": bot_state.settings.model_dump()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/preset/{preset}")
async def apply_preset(preset: str) -> Dict[str, Any]:
    """Apply a strategy preset."""
    try:
        bot_state.apply_preset(preset)
        return {
            "success": True,
            "preset": preset,
            "settings": bot_state.settings.model_dump()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
