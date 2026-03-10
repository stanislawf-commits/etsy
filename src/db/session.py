"""
session.py — engine SQLite i kontekst sesji.

Użycie:
    from src.db.session import get_session, init_db

    init_db()                    # jednorazowo przy starcie
    with get_session() as s:
        s.add(product)
        s.commit()
"""
import logging
from pathlib import Path
from contextlib import contextmanager
from typing import Generator

from sqlmodel import SQLModel, Session, create_engine

log = logging.getLogger(__name__)

DB_PATH = Path(__file__).parents[2] / "data" / "etsy3d.db"

_engine = None


def get_engine():
    global _engine
    if _engine is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(
            f"sqlite:///{DB_PATH}",
            echo=False,
            connect_args={"check_same_thread": False},
        )
    return _engine


def _apply_migrations() -> None:
    """
    Dodaje nowe kolumny do istniejących tabel (SQLite nie obsługuje ALTER w create_all).
    Idempotentne — ignoruje OperationalError przy duplikacie kolumny.
    """
    from sqlalchemy import text

    new_columns = [
        ("product", "stock_quantity",    "INTEGER NOT NULL DEFAULT 999"),
        ("product", "restock_threshold", "INTEGER NOT NULL DEFAULT 3"),
        ("product", "last_sold_at",      "DATETIME"),
    ]
    with Session(get_engine()) as session:
        for table, col, col_def in new_columns:
            try:
                session.exec(text(f"ALTER TABLE {table} ADD COLUMN {col} {col_def}"))  # type: ignore[call-overload]
                session.commit()
                log.info("Migration: added %s.%s", table, col)
            except Exception:
                session.rollback()  # kolumna już istnieje — ignoruj


def init_db() -> None:
    """Tworzy wszystkie tabele jeśli nie istnieją. Idempotentne."""
    from src.db.models import Product, RenderJob, ListingStats, StockEvent  # noqa: F401
    SQLModel.metadata.create_all(get_engine())
    _apply_migrations()
    log.info("DB initialized: %s", DB_PATH)


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Context manager zwracający sesję SQLModel."""
    with Session(get_engine()) as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
