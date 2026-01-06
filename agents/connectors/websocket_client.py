"""
Polymarket WebSocket Client.

Provides market and user feed connections with callback hooks and reconnects.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional
import inspect

import websockets


MarketCallback = Callable[[Dict[str, Any]], Optional[Awaitable[None]]]


class PolymarketWebSocketClient:
    MARKET_WS_URI = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    USER_WS_URI = "wss://ws-subscriptions-clob.polymarket.com/ws/user"

    def __init__(
        self,
        on_market_update: Optional[MarketCallback] = None,
        on_user_update: Optional[MarketCallback] = None,
        reconnect_delay: float = 5.0,
        max_reconnect_delay: float = 60.0,
        ping_interval: float = 5.0,
        ping_timeout: Optional[float] = None,
    ) -> None:
        self.on_market_update = on_market_update
        self.on_user_update = on_user_update
        self.reconnect_delay = reconnect_delay
        self.max_reconnect_delay = max_reconnect_delay
        self.ping_interval = ping_interval
        self.ping_timeout = ping_timeout

        self._stop_event = asyncio.Event()
        self._market_tasks: List[asyncio.Task] = []
        self._user_task: Optional[asyncio.Task] = None

    async def connect_market_feed(
        self,
        token_ids: List[str],
        chunk_size: int = 25,
    ) -> None:
        self._stop_event.clear()
        self._market_tasks = []

        for chunk in _chunk_list(token_ids, chunk_size):
            task = asyncio.create_task(
                self._connect_and_listen(
                    uri=self.MARKET_WS_URI,
                    subscribe_message={"assets_ids": chunk},
                    callback=self.on_market_update,
                )
            )
            self._market_tasks.append(task)

        if self._market_tasks:
            await asyncio.gather(*self._market_tasks)

    async def connect_user_feed(self, auth_message: Dict[str, Any]) -> None:
        self._stop_event.clear()
        self._user_task = asyncio.create_task(
            self._connect_and_listen(
                uri=self.USER_WS_URI,
                subscribe_message=auth_message,
                callback=self.on_user_update,
            )
        )
        await self._user_task

    async def close(self) -> None:
        self._stop_event.set()
        tasks = [t for t in self._market_tasks if not t.done()]
        if self._user_task and not self._user_task.done():
            tasks.append(self._user_task)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _connect_and_listen(
        self,
        uri: str,
        subscribe_message: Dict[str, Any],
        callback: Optional[MarketCallback],
    ) -> None:
        attempt = 0
        while not self._stop_event.is_set():
            try:
                async with websockets.connect(
                    uri,
                    ping_interval=self.ping_interval,
                    ping_timeout=self.ping_timeout,
                ) as websocket:
                    await websocket.send(json.dumps(subscribe_message))
                    attempt = 0
                    while not self._stop_event.is_set():
                        message = await websocket.recv()
                        data = _safe_json_loads(message)
                        if data is not None and callback is not None:
                            await _run_callback(callback, data)
            except asyncio.CancelledError:
                raise
            except Exception:
                attempt += 1
                delay = min(self.max_reconnect_delay, self.reconnect_delay * (2**attempt))
                await asyncio.sleep(delay)


def _chunk_list(items: List[str], chunk_size: int) -> Iterable[List[str]]:
    if chunk_size <= 0:
        yield items
        return
    for i in range(0, len(items), chunk_size):
        yield items[i : i + chunk_size]


def _safe_json_loads(message: str) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(message)
    except json.JSONDecodeError:
        return None


async def _run_callback(callback: MarketCallback, data: Dict[str, Any]) -> None:
    result = callback(data)
    if inspect.isawaitable(result):
        await result
