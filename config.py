# MAYA Trading Bot — config.py
# ════════════════════════════════════════════════════════════════
# Copy config.example.py to config.py and adjust settings below.
# This file is in .gitignore — never commit it to GitHub.
# ════════════════════════════════════════════════════════════════

import os
from dataclasses import dataclass

# ── Trading mode ─────────────────────────────────────────────────────────────
TRADING_MODE = "paper"   # always paper in public version

# ── Watchlist — stocks to scan ────────────────────────────────────────────────
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
    rsi_oversold:    int   = 30      # RSI oversold threshold
    rsi_overbought:  int   = 70      # RSI overbought threshold
    min_confidence:  int   = 65      # minimum confidence to trade (0-100)
    macd_fast:       int   = 12
    macd_slow:       int   = 26
    macd_signal:     int   = 9
    candle_period:   str   = "15m"   # 1m, 5m, 15m, 30m, 1h, 1d
    lookback_bars:   int   = 100     # bars of history to use
    max_daily_trades: int  = 5       # 0 = unlimited

STRATEGY = StrategyConfig()

# ── Risk settings ─────────────────────────────────────────────────────────────
@dataclass
class RiskConfig:
    stop_loss_pct:      float = 0.0050   # 0.50% stop loss
    take_profit_pct:    float = 0.0100   # 1.00% take profit
    boost_tp_pct:       float = 0.0250   # 2.50% after win streak
    wins_to_boost:      int   = 3        # wins before TP boost
    halt_after_losses:  int   = 3        # halt after N consecutive losses
    resume_after_days:  int   = 1
    max_position_pct:   float = 0.05     # 5% of portfolio per trade
    max_open_positions: int   = 5        # max simultaneous positions
    max_daily_loss_pct: float = 0.05     # halt if down 5% today
    min_trade_interval: int   = 1800     # 30 min cooldown between trades

RISK = RiskConfig()

# ── Database & logging ────────────────────────────────────────────────────────
DB_PATH       = "maya.db"
LOG_FILE      = "bot.log"
LOG_LEVEL     = "INFO"
CANDLE_PERIOD = STRATEGY.candle_period
LOOKBACK_BARS = STRATEGY.lookback_bars
