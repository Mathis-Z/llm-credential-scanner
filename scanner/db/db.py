"""
DB module.
Provides common BaseModel and DB connection.
"""

import pathlib
import peewee as pw
from pubsub import pub

project_root = pathlib.Path(__file__).parent.parent

DB = pw.SqliteDatabase(project_root / 'scanner.db')

class BaseModel(pw.Model):
    class Meta:
        database = DB

    @classmethod
    def create(cls, **query):
        record = super().create(**query)
        pub.sendMessage(f'{cls.__name__}.created', record=record)
        return record


DB.connect(reuse_if_open=True)
