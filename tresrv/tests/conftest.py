"""Test configuration for SQLite pragma setup."""
from sqlalchemy import event, Engine
from sqlalchemy.pool import StaticPool


@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    """Enable SQLite constraints and features needed for tests."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()
