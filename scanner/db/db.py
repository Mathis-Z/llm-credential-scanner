"""
DB module.
Provides common BaseModel and DB connection.
"""

import threading
import pathlib
from playhouse.pool import PooledSqliteDatabase
import peewee as pw
from pubsub import pub

project_root = pathlib.Path(__file__).parent.parent

DB = PooledSqliteDatabase(
    project_root / 'scanner.db',
    max_connections=16,
    stale_timeout=300,
    pragmas={
        "journal_mode": "wal",
        "busy_timeout": 5000,
        "foreign_keys": 1,
    },
    check_same_thread=False
)


class BaseModel(pw.Model):
    class Meta:
        database = DB

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
