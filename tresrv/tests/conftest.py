"""Test configuration for SQLite pragma setup."""
import pytest
from unittest.mock import patch
from sqlalchemy import event, Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool


@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    """Enable SQLite constraints and features needed for tests."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


@pytest.fixture(autouse=True)
def patch_session_expire_on_commit(monkeypatch):
    """Patch Session to use expire_on_commit=False for all test sessions."""
    original_init = Session.__init__

    def patched_init(self, *args, **kwargs):
        kwargs['expire_on_commit'] = False
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(Session, '__init__', patched_init)
