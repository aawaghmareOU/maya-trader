"""
MAYA Trading Bot — server.py
==============================
Flask dashboard server.
Run: python server.py
Then open: http://localhost:5000
"""

import subprocess
import sys
import json
import logging
import re
from pathlib import Path
from datetime import datetime

from flask import Flask, jsonify, request, send_from_directory
import sqlite3

from config import DB_PATH, STOCK_SYMBOLS, STRATEGY, RISK, TRADING_MODE
from database import init_db

app = Flask(__name__, static_folder=".")
logger = logging.getLogger(__name__)

BOT_PROCESS = None
BASE_DIR    = Path(__file__).parent


# ── DB helper ─────────────────────────────────────────────────────────────────
def query(sql: str, params=()) -> list:
    db = BASE_DIR / DB_PATH
    if not db.exists():
        return []
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []
    finally:
        conn.close()


# ── Dashboard ─────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory(".", "dashboard.html")


# ── Bot control ───────────────────────────────────────────────────────────────
@app.route("/api/bot/start", methods=["POST"])
def bot_start():
    global BOT_PROCESS
    if BOT_PROCESS and BOT_PROCESS.poll() is None:
        return jsonify({"ok": False, "msg": "Bot already running"})
    BOT_PROCESS = subprocess.Popen(
        [sys.executable, "bot.py"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd=str(BASE_DIR)
    )
    logger.info(f"Bot started (PID {BOT_PROCESS.pid})")
    return jsonify({"ok": True, "pid": BOT_PROCESS.pid})


@app.route("/api/bot/stop", methods=["POST"])
def bot_stop():
    global BOT_PROCESS
    if BOT_PROCESS and BOT_PROCESS.poll() is None:
        BOT_PROCESS.terminate()
        BOT_PROCESS = None
        return jsonify({"ok": True})
    return jsonify({"ok": False, "msg": "Bot not running"})


@app.route("/api/status")
def api_status():
    global BOT_PROCESS
    running = BOT_PROCESS is not None and BOT_PROCESS.poll() is None
    db_ok   = (BASE_DIR / DB_PATH).exists()
    return jsonify({
        "ok":           True,
        "bot_running":  running,
        "trading_mode": TRADING_MODE,
        "db_exists":    db_ok,
        "symbols":      STOCK_SYMBOLS,
        "candle":       STRATEGY.candle_period,
        "confidence":   STRATEGY.min_confidence,
    })


# ── Data endpoints ────────────────────────────────────────────────────────────
@app.route("/api/positions")
def api_positions():
    rows = query("SELECT * FROM positions WHERE quantity>0")
    return jsonify({"ok": True, "count": len(rows), "positions": rows})


@app.route("/api/trades")
def api_trades():
    limit = int(request.args.get("limit", 50))
    rows  = query(
        "SELECT * FROM trades ORDER BY timestamp DESC LIMIT ?",
        (min(limit, 500),)
    )
    return jsonify(rows)


@app.route("/api/signals")
def api_signals():
    limit = int(request.args.get("limit", 0))
    if limit > 0:
        rows = query(
            "SELECT * FROM signals ORDER BY timestamp DESC LIMIT ?",
            (min(limit, 500),)
        )
        return jsonify(rows)
    # Latest per symbol
    rows = query("SELECT * FROM signals ORDER BY timestamp DESC LIMIT 200")
    seen, uniq = set(), []
    for r in rows:
        if r["symbol"] not in seen:
            seen.add(r["symbol"])
            uniq.append(r)
    return jsonify(uniq)


@app.route("/api/summary")
def api_summary():
    today_trades = query(
        "SELECT * FROM trades WHERE date(timestamp)=date('now') AND pnl IS NOT NULL"
    )
    wins   = [t for t in today_trades if (t.get("pnl") or 0) > 0]
    losses = [t for t in today_trades if (t.get("pnl") or 0) < 0]
    total_pnl = sum(t.get("pnl", 0) or 0 for t in today_trades)

    positions = query("SELECT * FROM positions WHERE quantity>0")

    return jsonify({
        "ok":            True,
        "day_pnl":       round(total_pnl, 2),
        "total_trades":  len(today_trades),
        "wins":          len(wins),
        "losses":        len(losses),
        "win_rate":      round(len(wins) / max(len(today_trades), 1) * 100, 1),
        "open_positions": len(positions),
        "equity":        50000 + total_pnl,
    })


@app.route("/api/equity")
def api_equity():
    rows = query(
        "SELECT date(timestamp) as d, "
        "50000 + SUM(pnl) as equity "
        "FROM trades WHERE pnl IS NOT NULL "
        "GROUP BY date(timestamp) ORDER BY d"
    )
    return jsonify(rows)


@app.route("/api/log")
def api_log():
    log_path = BASE_DIR / "bot.log"
    if not log_path.exists():
        return jsonify({"lines": []})
    lines = log_path.read_text(errors="replace").splitlines()
    return jsonify({"lines": lines[-100:]})


# ── Config endpoints ──────────────────────────────────────────────────────────
@app.route("/api/config")
def api_config():
    return jsonify({
        "ok": True,
        "config": {
            "trading_mode":    TRADING_MODE,
            "symbols":         STOCK_SYMBOLS,
            "candle_period":   STRATEGY.candle_period,
            "min_confidence":  STRATEGY.min_confidence,
            "stop_loss_pct":   RISK.stop_loss_pct * 100,
            "take_profit_pct": RISK.take_profit_pct * 100,
            "max_positions":   RISK.max_open_positions,
            "cooldown_min":    RISK.min_trade_interval // 60,
            "max_daily_trades": getattr(STRATEGY, "max_daily_trades", 0),
        }
    })


@app.route("/api/config/strategy", methods=["POST"])
def api_save_strategy():
    data       = request.json or {}
    config_path = BASE_DIR / "config.py"
    if not config_path.exists():
        return jsonify({"ok": False, "msg": "config.py not found"})

    cfg = config_path.read_text()

    replacements = {
        r"min_confidence:\s*int\s*=\s*\d+":   f"min_confidence:  int   = {int(data.get('min_confidence', 65))}",
        r"candle_period:\s*str\s*=\s*\"[^\"]*\"": f'candle_period:   str   = "{data.get("candle_period","15m")}"',
        r"max_daily_trades:\s*int\s*=\s*\d+": f"max_daily_trades: int  = {int(data.get('max_daily_trades', 5))}",
        r"stop_loss_pct:\s*float\s*=\s*[\d.]+": f"stop_loss_pct:      float = {float(data.get('stop_loss_pct',0.5))/100:.4f}",
        r"take_profit_pct:\s*float\s*=\s*[\d.]+": f"take_profit_pct:    float = {float(data.get('take_profit_pct',1.0))/100:.4f}",
        r"max_open_positions:\s*int\s*=\s*\d+": f"max_open_positions: int   = {int(data.get('max_positions', 5))}",
    }

    import re
    for pattern, replacement in replacements.items():
        cfg = re.sub(pattern, replacement, cfg)

    config_path.write_text(cfg)
    return jsonify({"ok": True, "msg": "Settings saved — restart bot to apply"})


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    init_db()
    logger.info("MAYA Server starting on http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, debug=False)
