from pathlib import Path

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings

_is_sqlite = "sqlite" in settings.database_url

engine = create_engine(
    settings.database_url,
    # The API and the worker are separate processes sharing one SQLite file:
    # wait for the other's write to finish instead of failing at once.
    connect_args={"check_same_thread": False, "timeout": 30} if _is_sqlite else {},
)


if _is_sqlite:
    @event.listens_for(engine, "connect")
    def _sqlite_wal(dbapi_conn, _record):
        # WAL lets the API keep reading (e.g. job progress) while the worker
        # writes, instead of readers and the writer blocking each other.
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from app import models  # noqa: F401  (ensure models are registered)

    if settings.database_url.startswith("sqlite:///"):
        Path(settings.database_url.replace("sqlite:///", "")).parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    _add_missing_columns()


def _add_missing_columns(bind=None):
    """create_all() never alters existing tables, so a database created by an
    older version would crash on new columns. Add any missing ones in place
    (with their scalar default) — enough for this app's additive changes
    without pulling in a migration framework."""
    bind = bind or engine
    inspector = inspect(bind)
    with bind.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not inspector.has_table(table.name):
                continue
            existing = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing:
                    continue
                col_type = column.type.compile(dialect=bind.dialect)
                default = column.default.arg if column.default is not None and column.default.is_scalar else None
                clause = ""
                if isinstance(default, bool):
                    clause = f" DEFAULT {int(default)}"
                elif isinstance(default, (int, float)):
                    clause = f" DEFAULT {default}"
                elif isinstance(default, str):
                    clause = " DEFAULT '" + default.replace("'", "''") + "'"
                conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {col_type}{clause}'))
