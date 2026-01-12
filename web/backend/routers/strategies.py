"""
Strategy Scanning API Router
"""

from fastapi import APIRouter, HTTPException, Query
from typing import List, Dict, Any

from services import trading_service
from state import bot_state

router = APIRouter(prefix="/strategies", tags=["strategies"])


@router.get("/opportunities/{strategy}")
async def scan_opportunities(
    strategy: str,
    min_edge: float = Query(0.5, description="Minimum edge percentage"),
    max_days: int = Query(365, description="Maximum days until resolution"),
    min_liquidity: float = Query(500, description="Minimum liquidity in USD"),
    limit: int = Query(10, description="Maximum opportunities to return"),
    sort_by: str = Query("annualized", description="Sort by: edge or annualized")
) -> List[Dict[str, Any]]:
    """Scan for opportunities for a specific strategy."""
    try:
        bot_state.log("scan", f"API scan request for {strategy}")

        if strategy == "fullset":
            return trading_service.scan_fullset_opportunities(
                min_edge_pct=min_edge,
                min_liquidity=min_liquidity,
                max_days=max_days,
                limit=limit,
                sort_by=sort_by
            )
        elif strategy == "endgame":
            return trading_service.scan_endgame_opportunities(
                min_liquidity=min_liquidity,
                max_days=max_days,
                limit=limit,
                sort_by=sort_by
            )
        elif strategy == "oracle":
            return trading_service.scan_oracle_opportunities(
                min_edge_pct=min_edge,
                limit=limit
            )
        elif strategy == "rewards":
            summary = trading_service.get_rewards_summary()
            return [summary]
        else:
            raise HTTPException(status_code=400, detail=f"Unknown strategy: {strategy}")

    except HTTPException:
        raise
    except Exception as e:
        bot_state.log("error", f"Scan error: {str(e)[:50]}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/all")
async def scan_all_strategies(
    limit: int = Query(5, description="Max opportunities per strategy")
) -> Dict[str, List[Dict[str, Any]]]:
    """Scan all enabled strategies and return top opportunities."""
    try:
        results = {}
        settings = bot_state.settings

        # Map risk to parameters
        risk = settings.risk_appetite
        min_edge = 2.0 - (risk * 1.5)
        max_days = int(30 + (risk * 335))

        if settings.strategies_enabled.get("fullset"):
            results["fullset"] = trading_service.scan_fullset_opportunities(
                min_edge_pct=min_edge,
                max_days=max_days,
                limit=limit
            )

        if settings.strategies_enabled.get("endgame"):
            results["endgame"] = trading_service.scan_endgame_opportunities(
                min_liquidity=500,
                max_days=max_days,
                limit=limit
            )

        if settings.strategies_enabled.get("oracle"):
            results["oracle"] = trading_service.scan_oracle_opportunities(
                min_edge_pct=1.0,
                limit=limit
            )

        return results

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
