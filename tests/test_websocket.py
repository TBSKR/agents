"""
WebSocket smoke test for Polymarket market feeds.

Usage:
    python -m tests.test_websocket
    pytest tests/test_websocket.py -v -s
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from agents.connectors.websocket_client import PolymarketWebSocketClient
from agents.polymarket.gamma import GammaMarketClient


TIMEOUT_SECONDS = 30
MAX_MESSAGES = 20
NUM_MARKETS = 5


async def get_test_token_ids(count: int = NUM_MARKETS) -> List[str]:
    """
    Fetch active market token IDs for testing.

    Falls back to hardcoded IDs if Gamma fetch fails.
    """
    try:
        gamma = GammaMarketClient()
        markets = gamma.get_markets(
            querystring_params={
                "active": True,
                "closed": False,
                "archived": False,
                "limit": count * 2,
            }
        )
        token_ids = _extract_token_ids_from_markets(markets, count=count)
        if token_ids:
            print(f"OK: fetched {len(token_ids)} token ids from Gamma")
            return token_ids
    except Exception as exc:
        print(f"WARN: Gamma fetch failed: {exc}")

    print("WARN: using fallback token ids")
    return [
        "21742633143463906290569050155826241533067272736897614950488156847949938836455",
    ]


def _extract_token_ids_from_markets(
    markets: List[Dict[str, Any]],
    count: int,
) -> List[str]:
    token_ids: List[str] = []
    for market in markets:
        ids = _extract_market_token_ids(market)
        for token_id in ids:
            if token_id not in token_ids:
                token_ids.append(token_id)
            if len(token_ids) >= count:
                return token_ids[:count]
    return token_ids[:count]


def _extract_market_token_ids(market: Dict[str, Any]) -> List[str]:
    clob_ids = _parse_token_list(market.get("clobTokenIds"))
    if clob_ids:
        return [str(clob_ids[0])]

    token_objects = _parse_token_list(market.get("tokens"))
    if token_objects:
        first = token_objects[0]
        if isinstance(first, dict):
            for key in ("token_id", "tokenId", "id"):
                if key in first:
                    return [str(first[key])]
        if isinstance(first, str):
            return [first]
    return []


def _parse_token_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        if isinstance(parsed, list):
            return parsed
    return []


def _extract_asset_id(data: Any) -> Optional[str]:
    if isinstance(data, dict):
        asset_id = data.get("asset_id") or data.get("assetId") or data.get("market")
        return str(asset_id) if asset_id is not None else None
    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, dict):
            asset_id = first.get("asset_id") or first.get("assetId") or first.get("market")
            return str(asset_id) if asset_id is not None else None
    return None


async def run_smoke_test() -> bool:
    print("=" * 60)
    print("WebSocket Smoke Test")
    print("=" * 60)

    print("\n[1/5] Fetching test market tokens...")
    token_ids = await get_test_token_ids()
    if not token_ids:
        print("FAIL: no token ids available")
        return False
    print(f"OK: using {len(token_ids)} markets")

    messages_received = 0
    unique_assets = set()
    start_time = time.monotonic()

    def on_market_update(data: Dict[str, Any]) -> None:
        nonlocal messages_received, unique_assets
        messages_received += 1
        asset_id = _extract_asset_id(data)
        if asset_id:
            unique_assets.add(asset_id)
        if messages_received <= 5:
            elapsed = time.monotonic() - start_time
            asset_preview = (asset_id or "unknown")[:8]
            keys_preview = list(data.keys())[:3] if isinstance(data, dict) else []
            print(
                f"  [{elapsed:.1f}s] Message #{messages_received}: "
                f"asset={asset_preview} keys={keys_preview}"
            )

    print("\n[2/5] Creating WebSocket client...")
    client = PolymarketWebSocketClient(
        on_market_update=on_market_update,
        reconnect_delay=2.0,
        max_reconnect_delay=10.0,
    )
    print("OK: client created")

    print("\n[3/5] Connecting to market feed...")
    print(f"  Timeout: {TIMEOUT_SECONDS}s")
    print(f"  Max messages: {MAX_MESSAGES}")

    connect_task = asyncio.create_task(client.connect_market_feed(token_ids))
    try:
        start = time.monotonic()
        while True:
            elapsed = time.monotonic() - start
            if messages_received >= MAX_MESSAGES:
                print(f"\nOK: received {MAX_MESSAGES} messages, stopping test")
                break
            if elapsed >= TIMEOUT_SECONDS:
                print(f"\nOK: timeout reached ({TIMEOUT_SECONDS}s), stopping test")
                break
            await asyncio.sleep(0.5)
    except Exception as exc:
        print(f"\nFAIL: error during test: {exc}")
        await client.close()
        connect_task.cancel()
        await asyncio.gather(connect_task, return_exceptions=True)
        return False

    print("\n[4/5] Closing connection...")
    await client.close()
    connect_task.cancel()
    await asyncio.gather(connect_task, return_exceptions=True)
    print("OK: connection closed")

    print("\n[5/5] Test Results")
    print("-" * 60)
    elapsed_total = time.monotonic() - start_time
    messages_per_second = messages_received / elapsed_total if elapsed_total else 0.0
    print(f"  Duration: {elapsed_total:.1f}s")
    print(f"  Messages received: {messages_received}")
    print(f"  Unique assets: {len(unique_assets)}")
    print(f"  Messages/second: {messages_per_second:.2f}")

    success = messages_received > 0
    if success:
        print("\nPASS: smoke test completed successfully")
    else:
        print("\nFAIL: no messages received")

    print("=" * 60)
    return success


def test_websocket_smoke() -> None:
    success = asyncio.run(run_smoke_test())
    assert success


def main() -> None:
    try:
        success = asyncio.run(run_smoke_test())
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\nTest interrupted by user")
        sys.exit(1)
    except Exception as exc:
        print(f"\nTest failed with exception: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
