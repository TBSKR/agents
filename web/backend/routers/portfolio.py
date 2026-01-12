"""
Portfolio API Router
"""

from fastapi import APIRouter, HTTPException
from typing import List, Dict, Any

from services import trading_service
from schemas import PortfolioSummary, Position

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


@router.get("", response_model=PortfolioSummary)
async def get_portfolio():
    """Get current portfolio summary."""
    try:
        summary = trading_service.get_portfolio_summary()
        return PortfolioSummary(**summary)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/positions")
async def get_positions() -> List[Dict[str, Any]]:
    """Get all open positions."""
    try:
        return trading_service.get_positions()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/positions/{token_id}/close")
async def close_position(token_id: str) -> Dict[str, Any]:
    """Close a specific position."""
    try:
        result = trading_service.close_position(token_id)
        if not result.get("success"):
            raise HTTPException(status_code=400, detail=result.get("error", "Failed to close position"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/update-prices")
async def update_prices() -> Dict[str, Any]:
    """Update all position prices from market."""
    try:
        return trading_service.update_position_prices()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
