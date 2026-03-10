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


def init_db() -> None:
    """Tworzy wszystkie tabele jeśli nie istnieją. Idempotentne."""
    from src.db.models import Product, RenderJob, ListingStats  # noqa: F401 — rejestracja tabel
    SQLModel.metadata.create_all(get_engine())
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
