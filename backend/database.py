"""Database connection handling (MySQL via PyMySQL).
Configure with environment variables (defaults shown):
  DB_HOST=localhost  DB_PORT=3306  DB_USER=root  DB_PASSWORD=(empty)  DB_NAME=hospital_capacity
"""
import os
from contextlib import contextmanager

import pymysql
from pymysql.cursors import DictCursor

DB_CONFIG = dict(
    host=os.getenv("DB_HOST", "localhost"),
    port=int(os.getenv("DB_PORT", "3306")),
    user=os.getenv("DB_USER", "root"),
    password=os.getenv("DB_PASSWORD", ""),
    database=os.getenv("DB_NAME", "hospital_capacity"),
    charset="utf8mb4",
    cursorclass=DictCursor,
    autocommit=False,
    init_command="SET time_zone = '+00:00'",   # store and read everything in UTC
)


def init_pool():
    """Fail fast at startup if the database is unreachable."""
    pymysql.connect(**DB_CONFIG).close()


def close_pool():
    pass  # connections are opened per transaction, nothing to close


@contextmanager
def get_cursor():
    """One transaction per `with` block: commits on success, rolls back on error."""
    conn = pymysql.connect(**DB_CONFIG)
    try:
        with conn.cursor() as cur:
            yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
