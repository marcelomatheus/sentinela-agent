"""One PostgreSQL listener per API process, with durable SSE fallbacks.

NOTIFY carries only the conversation UUID. Messages remain in app.web_events,
so a disconnected listener cannot lose analysis results.
"""
import asyncio
import logging
from collections import defaultdict
from uuid import UUID

from psycopg import AsyncConnection

from sentinela.config import Settings

log = logging.getLogger(__name__)


class WebEventBus:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._subscribers: dict[UUID, set[asyncio.Event]] = defaultdict(set)
        self._task: asyncio.Task[None] | None = None

    def subscribe(self, conversation_id: UUID) -> asyncio.Event:
        event = asyncio.Event()
        self._subscribers[conversation_id].add(event)
        return event

    def unsubscribe(self, conversation_id: UUID, event: asyncio.Event) -> None:
        subscribers = self._subscribers.get(conversation_id)
        if subscribers is not None:
            subscribers.discard(event)
            if not subscribers:
                self._subscribers.pop(conversation_id, None)

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._listen(), name="sentinela-web-events")

    async def close(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _listen(self) -> None:
        while True:
            try:
                settings = self.settings
                async with await AsyncConnection.connect(
                    host=settings.postgres_host,
                    port=settings.postgres_port,
                    user=settings.postgres_user,
                    password=settings.postgres_password.get_secret_value(),
                    dbname=settings.postgres_db,
                    autocommit=True,
                    connect_timeout=5,
                ) as conn:
                    await conn.execute("LISTEN sentinela_web_events")
                    async for notification in conn.notifies():
                        try:
                            conversation = UUID(notification.payload)
                        except ValueError:
                            continue
                        for event in tuple(self._subscribers.get(conversation, ())):
                            event.set()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("web_event_listener_disconnected")
                await asyncio.sleep(2)
