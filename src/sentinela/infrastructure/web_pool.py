"""Small bounded PostgreSQL pool with explicit transaction boundaries.

Avoids opening a new TCP/Postgres connection on every web API call or SSE poll,
without introducing a new production dependency.
"""
from contextlib import contextmanager
from queue import Empty, Full, LifoQueue
from threading import BoundedSemaphore
from typing import Iterator

from psycopg import Connection
from psycopg.rows import dict_row

from sentinela.config import Settings


class BoundedWebPool:
    def __init__(self, settings: Settings, size: int = 6) -> None:
        self.settings = settings
        self.limit = BoundedSemaphore(size)
        self.idle: LifoQueue[Connection] = LifoQueue(maxsize=size)

    def _new(self) -> Connection:
        s=self.settings
        from psycopg import connect
        return connect(
            host=s.postgres_host,port=s.postgres_port,user=s.postgres_user,
            password=s.postgres_password.get_secret_value(),dbname=s.postgres_db,
            row_factory=dict_row,connect_timeout=5,
        )

    @contextmanager
    def connection(self) -> Iterator[Connection]:
        if not self.limit.acquire(timeout=5):
            raise TimeoutError("database pool saturated")
        connection = None
        try:
            try:
                connection = self.idle.get_nowait()
            except Empty:
                connection = self._new()
            if connection.closed or connection.broken:
                connection = self._new()
            try:
                yield connection
                connection.commit()
            except BaseException:
                try:
                    connection.rollback()
                except Exception:
                    connection.close()
                raise
        finally:
            if connection is not None and not connection.closed and not connection.broken:
                try:
                    self.idle.put_nowait(connection)
                except Full:
                    connection.close()
            self.limit.release()

    def close(self) -> None:
        while True:
            try:
                self.idle.get_nowait().close()
            except Empty:
                return
