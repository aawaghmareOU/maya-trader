"""
MAYA Trading Bot — database.py
================================
SQLite trade logging and position tracking.
"""

import sqlite3
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime

from config import DB_PATH

logger = logging.getLogger(__name__)


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create tables if they don't exist."""
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS trades (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp   TEXT,
                symbol      TEXT,
                asset_type  TEXT DEFAULT 'stock',
                side        TEXT,
                quantity    REAL,
                price       REAL,
                mode        TEXT DEFAULT 'paper',
                status      TEXT DEFAULT 'FILLED',
                order_id    TEXT,
                pnl         REAL,
                notes       TEXT
            );

            CREATE TABLE IF NOT EXISTS positions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol      TEXT UNIQUE,
                asset_type  TEXT DEFAULT 'stock',
                quantity    REAL DEFAULT 0,
                avg_price   REAL DEFAULT 0,
                stop_loss   REAL,
                take_profit REAL,
                opened_at   TEXT
            );

            CREATE TABLE IF NOT EXISTS signals (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp   TEXT,
                symbol      TEXT,
                signal      TEXT,
                rsi         REAL,
                fast_ma     REAL,
                slow_ma     REAL,
                price       REAL,
                confidence  INTEGER DEFAULT 0,
                regime      TEXT    DEFAULT 'UNKNOWN',
                conditions  TEXT,
                acted_on    INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS daily_stats (
                date        TEXT PRIMARY KEY,
                equity      REAL,
                pnl         REAL DEFAULT 0,
                trades      INTEGER DEFAULT 0,
                wins        INTEGER DEFAULT 0,
                losses      INTEGER DEFAULT 0
            );
        """)
    logger.info("Database initialised")


def log_trade(symbol: str, asset_type: str, side: str, quantity: float,
              price: float, mode: str = "paper", status: str = "FILLED",
              order_id: str = "", pnl: float = None, notes: str = ""):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO trades (timestamp, symbol, asset_type, side, quantity, "
            "price, mode, status, order_id, pnl, notes) "
            "VALUES (datetime('now'), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (symbol, asset_type, side, quantity, price, mode, status,
             order_id, pnl, notes)
        )


def upsert_position(symbol: str, asset_type: str, quantity: float,
                    avg_price: float, stop_loss: float = None,
                    take_profit: float = None):
    with get_conn() as conn:
        if quantity <= 0:
            conn.execute("DELETE FROM positions WHERE symbol=?", (symbol,))
        else:
            conn.execute(
                "INSERT INTO positions (symbol, asset_type, quantity, avg_price, "
                "stop_loss, take_profit, opened_at) VALUES (?,?,?,?,?,?,datetime('now')) "
                "ON CONFLICT(symbol) DO UPDATE SET "
                "quantity=excluded.quantity, avg_price=excluded.avg_price, "
                "stop_loss=excluded.stop_loss, take_profit=excluded.take_profit",
                (symbol, asset_type, quantity, avg_price, stop_loss, take_profit)
            )


def get_position(symbol: str) -> Optional[Dict]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM positions WHERE symbol=? AND quantity>0", (symbol,)
        ).fetchone()
        return dict(row) if row else None


def get_positions() -> List[Dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM positions WHERE quantity>0"
        ).fetchall()
        return [dict(r) for r in rows]


def log_signal(symbol: str, signal: str, rsi: float, fast_ma: float,
               slow_ma: float, price: float,
               confidence: int = 0, regime: str = "UNKNOWN",
               conditions: dict = None):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO signals (timestamp, symbol, signal, rsi, fast_ma, "
            "slow_ma, price, confidence, regime, conditions) "
            "VALUES (datetime('now'), ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (symbol, signal, float(rsi), float(fast_ma), float(slow_ma),
             float(price), int(confidence), str(regime),
             json.dumps(conditions) if conditions else None)
        )


def get_recent_trades(limit: int = 50) -> List[Dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM trades ORDER BY timestamp DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_daily_pnl() -> float:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(pnl),0) as total FROM trades "
            "WHERE date(timestamp)=date('now') AND pnl IS NOT NULL"
        ).fetchone()
        return float(row["total"]) if row else 0.0


def get_equity_history(days: int = 30) -> List[Dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT date, equity FROM daily_stats ORDER BY date DESC LIMIT ?",
            (days,)
        ).fetchall()
        return [dict(r) for r in rows]
