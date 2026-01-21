"""
DB module.
Provides common BaseModel and DB connection.
"""
import os
from pathlib import Path
from playhouse.pool import PooledSqliteDatabase
import peewee as pw
from pubsub import pub
from scanner.settings import Settings

# Create a DatabaseProxy that will be bound later
# this is required for the tests because I want temporary DBs for each test
DB = pw.DatabaseProxy()

def init_db():
    """Initialize database connection and tables. Call after Settings is configured."""
    full_db_path = Path(os.getcwd()) / Settings().db_path
    
    real_db = PooledSqliteDatabase(
        full_db_path,
        max_connections=16,
        stale_timeout=300,
        pragmas={
            "journal_mode": "wal",
            "busy_timeout": 5000,
            "foreign_keys": 1,
        },
        check_same_thread=False
    )

    # Bind the proxy to the real database
    DB.initialize(real_db)

    # Now create tables
    from scanner.db.models import Service, Endpoint
    DB.create_tables([Service, Endpoint], safe=True)


class BaseModel(pw.Model):
    class Meta:
        database = DB  # Use the proxy, not DB()

    @classmethod
    def create(cls, **query):
        with DB.atomic():
            record = super().create(**query)
        pub.sendMessage(f'{cls.__name__}.created', record=record)
        return record


class DBConnectionMixin:
    def run(self):
        DB.connect(reuse_if_open=True)
        try:
            super().run()
        finally:
            DB.close()
