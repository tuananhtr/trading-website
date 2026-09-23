"""
database.py - Database layer supporting both SQLite (local dev) and PostgreSQL (production).
Set DATABASE_URL environment variable for PostgreSQL. Falls back to SQLite if not set.
"""
import os
from datetime import date, datetime
from typing import List, Optional

import pandas as pd
from sqlalchemy import (
    Column, String, Float, Date, DateTime, Integer,
    create_engine, UniqueConstraint, Index, text
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

# ---------------------------------------------------------------------------
# Engine — PostgreSQL in production (DATABASE_URL set), SQLite locally
# ---------------------------------------------------------------------------
DATABASE_URL = os.environ.get("DATABASE_URL", "")

if DATABASE_URL:
    # Railway / Render provide postgres:// — SQLAlchemy needs postgresql://
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    engine = create_engine(DATABASE_URL, echo=False, future=True)
    print(f"[DB] Using PostgreSQL")
else:
    DB_PATH = os.path.join(os.path.dirname(__file__), "stock_data.db")
    engine = create_engine(f"sqlite:///{DB_PATH}", echo=False, future=True,
                           connect_args={"check_same_thread": False})
    print(f"[DB] Using SQLite: {DB_PATH}")

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


# ---------------------------------------------------------------------------
# ORM models
# ---------------------------------------------------------------------------
class Base(DeclarativeBase):
    pass


class StockPrice(Base):
    __tablename__ = "stock_prices"

    id      = Column(Integer, primary_key=True, autoincrement=True)
    ticker  = Column(String(20), nullable=False)
    date    = Column(Date, nullable=False)
    open    = Column(Float)
    high    = Column(Float)
    low     = Column(Float)
    close   = Column(Float)
    volume  = Column(Float)

    __table_args__ = (
        UniqueConstraint("ticker", "date", name="uq_ticker_date"),
        Index("ix_ticker_date", "ticker", "date"),
    )


class WatchlistItem(Base):
    __tablename__ = "watchlist"

    id       = Column(Integer, primary_key=True, autoincrement=True)
    ticker   = Column(String(20), nullable=False, unique=True)
    added_at = Column(DateTime, default=datetime.utcnow)


def init_db():
    Base.metadata.create_all(bind=engine)


# ---------------------------------------------------------------------------
# OHLCV helpers
# ---------------------------------------------------------------------------

def upsert_ohlcv(df: pd.DataFrame, ticker: str) -> int:
    """Insert or replace OHLCV rows for *ticker*. Returns number of rows upserted."""
    if df.empty:
        return 0

    rows = df.reset_index() if df.index.name == "date" else df
    rows = rows.to_dict(orient="records")

    # Detect whether we're using PostgreSQL or SQLite for upsert syntax
    is_postgres = DATABASE_URL != ""

    with SessionLocal() as session:
        if is_postgres:
            # PostgreSQL upsert
            session.execute(
                text(
                    "INSERT INTO stock_prices (ticker, date, open, high, low, close, volume) "
                    "VALUES (:ticker, :date, :open, :high, :low, :close, :volume) "
                    "ON CONFLICT (ticker, date) DO UPDATE SET "
                    "open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low, "
                    "close=EXCLUDED.close, volume=EXCLUDED.volume"
                ),
                [{"ticker": ticker, "date": r.get("date"), "open": r.get("open"),
                  "high": r.get("high"), "low": r.get("low"),
                  "close": r.get("close"), "volume": r.get("volume")} for r in rows],
            )
        else:
            # SQLite upsert
            session.execute(
                text(
                    "INSERT OR REPLACE INTO stock_prices "
                    "(ticker, date, open, high, low, close, volume) VALUES "
                    "(:ticker, :date, :open, :high, :low, :close, :volume)"
                ),
                [{"ticker": ticker, "date": r.get("date"), "open": r.get("open"),
                  "high": r.get("high"), "low": r.get("low"),
                  "close": r.get("close"), "volume": r.get("volume")} for r in rows],
            )
        session.commit()

    return len(rows)


def get_ohlcv(ticker: str, start: Optional[date] = None, end: Optional[date] = None) -> pd.DataFrame:
    """Return stored OHLCV as a DataFrame, optionally filtered by date range."""
    with SessionLocal() as session:
        q = session.query(StockPrice).filter(StockPrice.ticker == ticker)
        if start:
            q = q.filter(StockPrice.date >= start)
        if end:
            q = q.filter(StockPrice.date <= end)
        q = q.order_by(StockPrice.date)
        rows = q.all()

    if not rows:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])

    df = pd.DataFrame(
        [{"date": r.date, "open": r.open, "high": r.high,
          "low": r.low, "close": r.close, "volume": r.volume}
         for r in rows]
    )
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")
    return df


def get_last_stored_date(ticker: str) -> Optional[date]:
    with SessionLocal() as session:
        row = session.query(StockPrice.date).filter(
            StockPrice.ticker == ticker
        ).order_by(StockPrice.date.desc()).first()
    return row[0] if row else None


def has_data(ticker: str) -> bool:
    with SessionLocal() as session:
        count = session.query(StockPrice).filter(StockPrice.ticker == ticker).count()
    return count > 0


# ---------------------------------------------------------------------------
# Watchlist helpers
# ---------------------------------------------------------------------------

def get_watchlist() -> List[str]:
    with SessionLocal() as session:
        items = session.query(WatchlistItem).order_by(WatchlistItem.added_at).all()
    return [i.ticker for i in items]


def add_to_watchlist(ticker: str) -> bool:
    with SessionLocal() as session:
        existing = session.query(WatchlistItem).filter(WatchlistItem.ticker == ticker).first()
        if existing:
            return False
        session.add(WatchlistItem(ticker=ticker, added_at=datetime.utcnow()))
        session.commit()
    return True


def remove_from_watchlist(ticker: str) -> bool:
    with SessionLocal() as session:
        item = session.query(WatchlistItem).filter(WatchlistItem.ticker == ticker).first()
        if not item:
            return False
        session.delete(item)
        session.commit()
    return True
