# MAYA Trading Bot — config.example.py
# ════════════════════════════════════════════════════════════════
# Copy this file to config.py and adjust the settings.
#
#   cp config.example.py config.py
#
# config.py is in .gitignore — it will never be committed.
# ════════════════════════════════════════════════════════════════

import os
from dataclasses import dataclass

# ── Trading mode (always paper in this version) ───────────────────────────────
TRADING_MODE = "paper"

# ── Watchlist — stocks to scan ────────────────────────────────────────────────
# Yahoo Finance symbols — any US stock ticker works
STOCK_SYMBOLS = [
    "NVDA", "AAPL", "MSFT", "GOOGL", "AMZN",
    "TSLA", "META", "QCOM", "MU", "TSM"
]

# ── Strategy settings ─────────────────────────────────────────────────────────
@dataclass
class StrategyConfig:
    fast_ma_period:  int   = 9       # fast EMA period
    slow_ma_period:  int   = 21      # slow EMA period
    rsi_period:      int   = 14      # RSI period
    rsi_oversold:    int   = 30
    rsi_overbought:  int   = 70
    min_confidence:  int   = 65      # 0-100, higher = fewer but stronger signals
    macd_fast:       int   = 12
    macd_slow:       int   = 26
    macd_signal:     int   = 9
    candle_period:   str   = "15m"   # 1m, 5m, 15m, 30m, 1h, 1d
    lookback_bars:   int   = 100
    max_daily_trades: int  = 5       # 0 = unlimited

STRATEGY = StrategyConfig()

# ── Risk settings ─────────────────────────────────────────────────────────────
@dataclass
class RiskConfig:
    stop_loss_pct:      float = 0.0050  # 0.5% — max loss per trade
    take_profit_pct:    float = 0.0100  # 1.0% — target profit per trade
    boost_tp_pct:       float = 0.0250  # 2.5% — TP after 3 consecutive wins
    wins_to_boost:      int   = 3
    halt_after_losses:  int   = 3
    resume_after_days:  int   = 1
    max_position_pct:   float = 0.05    # 5% of portfolio per trade
    max_open_positions: int   = 5
    max_daily_loss_pct: float = 0.05    # halt trading if down 5% today
    min_trade_interval: int   = 1800    # 30 min cooldown between trades on same stock

RISK = RiskConfig()

# ── Database & logging ────────────────────────────────────────────────────────
DB_PATH       = "maya.db"
LOG_FILE      = "bot.log"
LOG_LEVEL     = "INFO"
CANDLE_PERIOD = STRATEGY.candle_period
LOOKBACK_BARS = STRATEGY.lookback_bars
