"""PostgreSQL LISTEN/NOTIFY broadcaster for real-time sighting streaming."""

import asyncio
import json
import logging
from collections import defaultdict
from typing import Any

import asyncpg

from app.core.config import settings

logger = logging.getLogger("roadtrace.broadcaster")


class SightingBroadcaster:
    """Manages Postgres LISTEN/NOTIFY connection and fans out sighting events to WebSocket subscribers."""

    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._lock = asyncio.Lock()
        self._pg_conn: asyncpg.Connection | None = None
        self._listen_task: asyncio.Task | None = None
        self._running = False

    def _get_dsn(self) -> str:
        dsn = settings.database_url
        if dsn.startswith("postgresql+asyncpg://"):
            dsn = dsn.replace("postgresql+asyncpg://", "postgresql://", 1)
        return dsn

    async def start(self) -> None:
        """Start listening to Postgres NOTIFY events in the background."""
        if self._running:
            return
        self._running = True
        self._listen_task = asyncio.create_task(self._listen_loop())

    async def stop(self) -> None:
        """Stop listening and close Postgres connection."""
        self._running = False
        if self._listen_task:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
            self._listen_task = None

        if self._pg_conn and not self._pg_conn.is_closed():
            try:
                await self._pg_conn.close()
            except Exception as e:
                logger.warning(f"Error closing broadcaster connection: {e}")
            self._pg_conn = None

    def _on_notify(
        self,
        connection: asyncpg.Connection,
        pid: int,
        channel: str,
        payload: str,
    ) -> None:
        """Callback invoked by asyncpg on receipt of Postgres NOTIFY."""
        try:
            data = json.loads(payload)
            plate = str(data.get("plate_number", "")).strip().upper()
            self._dispatch(plate, data)
        except Exception as e:
            logger.error(f"Broadcaster failed to parse notify payload: {e}")

    def _dispatch(self, plate: str, data: dict[str, Any]) -> None:
        """Dispatch sighting data to all queues subscribed to plate."""
        queues = list(self._subscribers.get(plate, set()))
        # Also dispatch to wildcard '*' subscribers if any
        wildcard_queues = list(self._subscribers.get("*", set()))
        all_queues = set(queues + wildcard_queues)

        for q in all_queues:
            try:
                q.put_nowait(data)
            except asyncio.QueueFull:
                logger.warning(f"Queue full for plate {plate}, dropping event")

    async def publish_local(self, data: dict[str, Any]) -> None:
        """Publish sighting locally (useful in tests and direct emissions)."""
        plate = str(data.get("plate_number", "")).strip().upper()
        self._dispatch(plate, data)

    async def _listen_loop(self) -> None:
        """Continuous background loop keeping asyncpg LISTEN active."""
        dsn = self._get_dsn()
        while self._running:
            try:
                self._pg_conn = await asyncpg.connect(dsn)
                await self._pg_conn.add_listener("new_sighting", self._on_notify)
                logger.info("Broadcaster successfully connected and listening to 'new_sighting'")

                # Keep connection alive while running
                while self._running and not self._pg_conn.is_closed():
                    await asyncio.sleep(2.0)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Broadcaster connection error: {e}. Reconnecting in 2 seconds...")
                await asyncio.sleep(2.0)
            finally:
                if self._pg_conn and not self._pg_conn.is_closed():
                    try:
                        await self._pg_conn.remove_listener("new_sighting", self._on_notify)
                        await self._pg_conn.close()
                    except Exception:
                        pass
                    self._pg_conn = None

    async def subscribe(self, plate: str) -> asyncio.Queue:
        """Subscribe to sighting events for the specified plate."""
        norm_plate = plate.strip().upper()
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        async with self._lock:
            self._subscribers[norm_plate].add(q)
            if not self._running:
                await self.start()
        return q

    async def unsubscribe(self, plate: str, q: asyncio.Queue) -> None:
        """Unsubscribe queue from plate events."""
        norm_plate = plate.strip().upper()
        async with self._lock:
            if norm_plate in self._subscribers:
                self._subscribers[norm_plate].discard(q)
                if not self._subscribers[norm_plate]:
                    del self._subscribers[norm_plate]


broadcaster = SightingBroadcaster()
