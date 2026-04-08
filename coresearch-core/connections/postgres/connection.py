import os
import time
from contextlib import contextmanager

import psycopg2
import psycopg2.pool
from psycopg2.extras import RealDictCursor

_pool = None

_CONNECT_KWARGS = dict(
    host=os.getenv("POSTGRES_HOST", "host.docker.internal"),
    port=int(os.getenv("POSTGRES_PORT", 5432)),
    dbname=os.getenv("POSTGRES_DB", "coresearch"),
    user=os.getenv("POSTGRES_USER", "coresearch"),
    password=os.getenv("POSTGRES_PASSWORD", "coresearch"),
    connect_timeout=5,
    options="-c statement_timeout=30000",  # 30s query timeout
    keepalives=1,
    keepalives_idle=5,
    keepalives_interval=3,
    keepalives_count=3,
)


def _get_pool():
    global _pool
    if _pool is None or _pool.closed:
        for attempt in range(5):
            try:
                _pool = psycopg2.pool.ThreadedConnectionPool(
                    minconn=1, maxconn=10, **_CONNECT_KWARGS,
                )
                return _pool
            except psycopg2.OperationalError:
                if attempt < 4:
                    time.sleep(1)
                else:
                    raise
    return _pool


@contextmanager
def get_cursor(autocommit=True):
    pool = _get_pool()
    conn = pool.getconn()
    conn.autocommit = autocommit
    try:
        yield conn.cursor(cursor_factory=RealDictCursor)
        if not autocommit:
            conn.commit()
    except Exception:
        if not autocommit:
            conn.rollback()
        raise
    finally:
        pool.putconn(conn)
