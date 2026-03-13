"""
DB module.
Provides common BaseModel and DB connection.
"""
import os
import logging
import threading
import queue
from dataclasses import dataclass
from pathlib import Path
from playhouse.pool import PooledSqliteDatabase
import peewee as pw
from pubsub import pub
from scanner.settings import get_settings

logger = logging.getLogger("scanner.db")

# Create a DatabaseProxy that will be bound later
# this is required for the tests because I want temporary DBs for each test
DB = pw.DatabaseProxy()

DB_WRITE_TIMEOUT_SECONDS = 60
_DB_WRITE_CONTEXT = threading.local()


@dataclass
class _DBWriteTask:
    func: callable
    done_event: threading.Event
    result: object | None = None
    error: Exception | None = None


class DBWriteQueue:
    def __init__(self):
        self._queue: queue.Queue[_DBWriteTask | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def start(self):
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._thread = threading.Thread(target=self._run, name="db-writer", daemon=True)
            self._thread.start()

    def submit(self, func: callable, timeout: int | None = None):
        self.start()
        task = _DBWriteTask(func=func, done_event=threading.Event())
        self._queue.put(task)

        wait_timeout = timeout if timeout is not None else DB_WRITE_TIMEOUT_SECONDS
        if not task.done_event.wait(wait_timeout):
            raise TimeoutError(f"Database operation timed out after {wait_timeout} seconds")
        if task.error:
            raise task.error
        return task.result

    def _run(self):
        while True:
            task = self._queue.get()
            if task is None:
                break
            try:
                _DB_WRITE_CONTEXT.in_writer = True
                with DB.connection_context():
                    task.result = task.func()
            except Exception as exc:
                logger.error("Error in DB operation: %s", exc)
                task.error = exc
            finally:
                _DB_WRITE_CONTEXT.in_writer = False
                task.done_event.set()


DB_WRITE_QUEUE = DBWriteQueue()


def submit_db_write(func: callable, timeout: int | None = None):
    if getattr(_DB_WRITE_CONTEXT, "in_writer", False):
        return func()
    return DB_WRITE_QUEUE.submit(func, timeout=timeout)

def full_db_path(path: str | None = None) -> Path:
    return Path(os.getcwd()) / (path if path else get_settings().db_path)

def load_db(path: Path | str):
    """Load existing DB. Throws FileNotFoundError. Useful for debug shells."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Database file not found at {path}")

    real_db = PooledSqliteDatabase(
        path,
        max_connections=get_settings().db_max_connections,
        stale_timeout=300,
        pragmas={
            "journal_mode": "wal",
            "busy_timeout": 5000,
            "foreign_keys": 1,
        },
        check_same_thread=False
    )
    _init_db(real_db)

def create_db(path: Path | str):
    """Create new DB."""
    # creating the directory here is suboptimal but future work I guess
    path = Path(path)
    db_dir = path.parent
    if not db_dir.exists():
        logger.debug("Creating database directory at %s", db_dir)
        db_dir.mkdir(parents=True, exist_ok=True)

    real_db = PooledSqliteDatabase(
        path,
        max_connections=get_settings().db_max_connections,
        stale_timeout=300,
        pragmas={
            "journal_mode": "wal",
            "busy_timeout": 5000,
            "foreign_keys": 1,
        },
        check_same_thread=False
    )
    _init_db(real_db)

def _init_db(real_db: PooledSqliteDatabase):
    # Bind the proxy to the real database
    DB.initialize(real_db)
    DB_WRITE_QUEUE.start()
    from scanner.db.models import Service, Endpoint # avoid circular import
    DB.create_tables([Service, Endpoint], safe=True)

def load_or_create_db(path: str | None = None):
    """Initialize database connection and tables. Call after Settings is configured."""
    try:
        path = full_db_path(path)

        if path.exists():
            load_db(path)
        else:
            create_db(path)
    except pw.OperationalError as e:
        logger.critical("Failed to initialize database at %s: %s", path, e)
        raise e

class BaseModel(pw.Model):
    class Meta:
        database = DB  # Use the proxy, not DB()

    @classmethod
    def create(cls, **query):
        def _create():
            with DB.atomic():
                return super(BaseModel, cls).create(**query)

        record = submit_db_write(_create)
        pub.sendMessage(f"{cls.__name__}.created", record=record)
        return record

    @classmethod
    def get_or_create(cls, **query):
        defaults = query.pop("defaults", None)

        def _get_or_create():
            with DB.atomic():
                try:
                    return super(BaseModel, cls).get(**query), False
                except cls.DoesNotExist:
                    create_data = dict(query)
                    if defaults:
                        create_data.update(defaults)
                    return super(BaseModel, cls).create(**create_data), True

        record, created = submit_db_write(_get_or_create)
        if created:
            pub.sendMessage(f"{cls.__name__}.created", record=record)
        return record, created

    def save(self, *args, **kwargs):
        def _save():
            with DB.atomic():
                return super(BaseModel, self).save(*args, **kwargs)

        return submit_db_write(_save)


class DBConnectionMixin:
    def run(self):
        run_with_db = getattr(self, "run_with_db", None)
        if not callable(run_with_db):
            raise NotImplementedError("run_with_db must be implemented by DBConnectionMixin subclasses")

        with DB.connection_context():
            return run_with_db()
