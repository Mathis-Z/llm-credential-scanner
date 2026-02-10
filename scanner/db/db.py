"""
DB module.
Provides common BaseModel and DB connection.
"""
import os
import logging
from pathlib import Path
from playhouse.pool import PooledSqliteDatabase
import peewee as pw
from pubsub import pub
from scanner.settings import Settings

logger = logging.getLogger("scanner.db")

# Create a DatabaseProxy that will be bound later
# this is required for the tests because I want temporary DBs for each test
DB = pw.DatabaseProxy()

def init_db():
    """Initialize database connection and tables. Call after Settings is configured."""
    try:
        full_db_path = Path(os.getcwd()) / Settings().db_path
        # creating the directory here is suboptimal but future work I guess
        db_dir = full_db_path.parent
        if not db_dir.exists():
            logger.debug("Creating database directory at %s", db_dir)
            db_dir.mkdir(parents=True, exist_ok=True)

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
    except pw.OperationalError as e:
        logger.critical("Failed to initialize database at %s: %s", full_db_path, e)
        exit()

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
