# Database module providing SQLite connection, write queue, and base model classes.

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

# DatabaseProxy allows late binding - required for tests with temporary DBs
DB = pw.DatabaseProxy()

DB_WRITE_TIMEOUT_SECONDS = 60
_DB_WRITE_CONTEXT = threading.local()


@dataclass
class _DBWriteTask:
    """Task wrapper for async database writes via queue."""
    func: callable
    done_event: threading.Event
    result: object | None = None
    error: Exception | None = None


class DBWriteQueue:
    """
    Serializes database writes through a dedicated writer thread.
    
    All writes go through a single thread to avoid SQLite locking issues
    when multiple scanner modules access the DB concurrently.
    """
    def __init__(self):
        self._queue: queue.Queue[_DBWriteTask | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def start(self):
        """Start the writer thread if not already running."""
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._thread = threading.Thread(target=self._run, name="db-writer", daemon=True)
            self._thread.start()

    def submit(self, func: callable, timeout: int | None = None):
        """Submit a write operation and wait for completion."""
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
        """Writer thread that processes queued write operations."""
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
    """Submit write operation to queue, or execute directly if already in writer thread."""
    if getattr(_DB_WRITE_CONTEXT, "in_writer", False):
        return func()
    return DB_WRITE_QUEUE.submit(func, timeout=timeout)

def full_db_path(path: str | None = None) -> Path:
    """Resolve absolute path for database file."""
    return Path(os.getcwd()) / (path if path else get_settings().db_path)

def load_db(path: Path | str):
    """Load existing database file. Raises FileNotFoundError if not found."""
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
    """Create new database with directory if needed."""
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
    """Bind proxy to database, start write queue, create tables."""
    DB.initialize(real_db)
    DB_WRITE_QUEUE.start()
    from scanner.db.models import Service, Endpoint  # avoid circular import
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
    """Base model with async write queue and pubsub notifications."""
    class Meta:
        database = DB  # Use the proxy, not DB()

    @classmethod
    def create(cls, **query):
        """Create record via write queue and publish creation event."""
        def _create():
            with DB.atomic():
                return super(BaseModel, cls).create(**query)

        record = submit_db_write(_create)
        pub.sendMessage(f"{cls.__name__}.created", record=record)
        return record

    @classmethod
    def get_or_create(cls, **query):
        """Get existing or create new record via write queue."""
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
        """Save record via write queue."""
        def _save():
            with DB.atomic():
                return super(BaseModel, self).save(*args, **kwargs)

        return submit_db_write(_save)


class DBConnectionMixin:
    """Mixin for threads that need database access within a connection context."""
    def run(self):
        """
        Entry point for thread execution with database connection context.
        
        Subclasses must implement run_with_db() which will be called
        with an active database connection.
        """
        run_with_db = getattr(self, "run_with_db", None)
        if not callable(run_with_db):
            raise NotImplementedError("run_with_db must be implemented by DBConnectionMixin subclasses")

        with DB.connection_context():
            return run_with_db()
