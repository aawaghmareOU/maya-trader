"""
MAYA Trading Bot — bot.py
===========================
Ladder strategy with regime-aware signals.

How it works:
  1. Scans watchlist every 60 seconds on 15m candles
  2. Computes EMA + RSI + MACD confidence score
  3. Checks 5 conditions before entering a trade
  4. Manages SL/TP exits automatically
  5. Logs everything to SQLite database
"""

import time
import logging
import logging.handlers
from datetime import datetime
from typing import Dict

from config import (
    STOCK_SYMBOLS, TRADING_MODE, RISK, STRATEGY,
    DB_PATH, LOG_FILE, LOG_LEVEL, LOOKBACK_BARS
)
from database import (
    init_db, log_trade, log_signal,
    upsert_position, get_position, get_positions
)
from strategy import compute_signal
from broker_yahoo import get_stock_broker

# ── Logging setup ─────────────────────────────────────────────────────────────
logger = logging.getLogger(__name__)


def setup_logging():
    level = getattr(logging, LOG_LEVEL.upper(), logging.INFO)
    fmt   = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    # File handler with rotation
    fh = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=3
    )
    fh.setFormatter(fmt)

    # Console handler
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(fh)
    root.addHandler(ch)


# ── Risk manager (inline, no separate file needed) ────────────────────────────
class RiskManager:
    def approve_trade(self, symbol: str, portfolio_value: float,
                      price: float) -> tuple:
        positions = get_positions()
        if len(positions) >= RISK.max_open_positions:
            return False, f"Max positions reached ({RISK.max_open_positions})"
        if price <= 0:
            return False, "Invalid price"
        return True, "OK"

    def position_size(self, portfolio_value: float, price: float) -> float:
        qty = (portfolio_value * RISK.max_position_pct) / price
        return round(max(qty, 1.0), 4)

    def should_exit(self, symbol: str, price: float,
                    stop_loss: float, take_profit: float) -> str:
        if stop_loss and price <= stop_loss:
            return "STOP_LOSS"
        if take_profit and price >= take_profit:
            return "TAKE_PROFIT"
        return ""


# ── Trading bot ───────────────────────────────────────────────────────────────
class TradingBot:

    def __init__(self):
        self.risk              = RiskManager()
        self._last_traded:     Dict[str, float] = {}
        self._daily_losses:    Dict[str, int]   = {}
        self._daily_trade_count: int = 0
        self._last_reset_date: str  = ""

    def run(self):
        """Main loop — scans every 60 seconds."""
        logger.info(f"[BOT] MAYA Trading Bot starting in [{TRADING_MODE.upper()}] mode")
        logger.info(f"[BOT] Watching {len(STOCK_SYMBOLS)} symbols | "
                    f"Candle: {STRATEGY.candle_period} | "
                    f"Confidence: {STRATEGY.min_confidence}%")

        broker = get_stock_broker()
        logger.info(f"[BOT] Scanning every 60s. Press Ctrl+C to stop.")

        while True:
            try:
                self.tick(broker)
                time.sleep(60)
            except KeyboardInterrupt:
                logger.info("[BOT] Stopped by user")
                break
            except Exception as e:
                logger.error(f"[BOT] Tick error: {e}", exc_info=True)
                time.sleep(30)

    def tick(self, broker):
        """One full scan of all symbols."""
        logger.info("--- Tick started ---")

        # Reset daily counters at start of new day
        today = datetime.now().strftime("%Y-%m-%d")
        if today != self._last_reset_date:
            self._daily_losses      = {}
            self._daily_trade_count = 0
            self._last_reset_date   = today
            logger.info("[BOT] Daily counters reset")

        portfolio_value = broker.get_portfolio_value()

        for symbol in STOCK_SYMBOLS:
            try:
                self._process_symbol(symbol, "stock", broker, portfolio_value)
            except Exception as e:
                logger.error(f"[{symbol}] Error: {e}", exc_info=True)

        logger.info("--- Tick complete ---")
        logger.info(f"[BOT] Sleeping 60s until next scan")

    def _process_symbol(self, symbol: str, asset_type: str,
                        broker, portfolio_value: float):

        # ── Check exit on open positions FIRST (before any cooldown) ──────────
        position = get_position(symbol)
        if position and position["quantity"] > 0:
            closes = broker.get_historical_closes(symbol, LOOKBACK_BARS)
            if closes:
                current_price = closes[-1]
                exit_reason   = self.risk.should_exit(
                    symbol, current_price,
                    position.get("stop_loss"),
                    position.get("take_profit")
                )
                if exit_reason:
                    self._execute_sell(symbol, asset_type, broker,
                                       position, current_price,
                                       portfolio_value, exit_reason)
                    return

        # ── Daily trade limit ─────────────────────────────────────────────────
        max_t = getattr(STRATEGY, "max_daily_trades", 0)
        if max_t > 0 and self._daily_trade_count >= max_t:
            logger.info(f"[{symbol}] Daily trade limit ({max_t}) reached")
            return

        # ── Daily loss limit per symbol ───────────────────────────────────────
        if self._daily_losses.get(symbol, 0) >= 2:
            logger.info(f"[{symbol}] Daily loss limit — skipping")
            return

        # ── Cooldown between trades ───────────────────────────────────────────
        now  = time.time()
        last = self._last_traded.get(symbol, 0)
        if now - last < RISK.min_trade_interval:
            remaining = int(RISK.min_trade_interval - (now - last))
            logger.info(f"[{symbol}] Cooldown {remaining}s remaining")
            return

        # ── Fetch price history ───────────────────────────────────────────────
        closes = broker.get_historical_closes(symbol, LOOKBACK_BARS)
        if len(closes) < 30:
            logger.warning(f"[{symbol}] Insufficient history ({len(closes)} bars)")
            return

        current_price = closes[-1]

        # ── Compute signal ────────────────────────────────────────────────────
        result = compute_signal(closes, symbol)

        log_signal(
            symbol, result.signal, result.rsi,
            result.fast_ma, result.slow_ma, current_price,
            confidence=result.confidence,
            regime=result.regime,
            conditions={
                "regime":     result.cond_regime,
                "confidence": result.cond_confidence,
                "ma_cross":   result.cond_ma_cross,
                "rsi":        result.cond_rsi,
                "trades":     result.cond_trades,
                "met":        result.conditions_met,
            }
        )

        # ── Act on signal (BUY only — exits handled above via SL/TP) ─────────
        if result.signal == "BUY" and (not position or position["quantity"] == 0):
            self._execute_buy(symbol, asset_type, broker,
                              current_price, portfolio_value, result)
        elif result.signal == "SELL" and position and position["quantity"] > 0:
            logger.info(f"[{symbol}] Strategy SELL noted — exits via SL/TP only")

    def _execute_buy(self, symbol: str, asset_type: str, broker,
                     price: float, portfolio_value: float, signal_result):
        approved, reason = self.risk.approve_trade(symbol, portfolio_value, price)
        if not approved:
            logger.info(f"[{symbol}] BUY blocked: {reason}")
            return

        quantity = self.risk.position_size(portfolio_value, price)
        stop     = round(price * (1 - RISK.stop_loss_pct), 4)
        target   = round(price * (1 + RISK.take_profit_pct), 4)

        success, order_id = broker.place_market_order(symbol, "BUY", quantity)
        status = "FILLED" if success else "REJECTED"

        log_trade(symbol, asset_type, "BUY", quantity, price,
                  TRADING_MODE, status, order_id,
                  notes=signal_result.reason)

        if success:
            self._daily_trade_count += 1
            upsert_position(symbol, asset_type, quantity, price, stop, target)
            self._last_traded[symbol] = time.time()
            logger.info(
                f"OK: [{symbol}] BUY {quantity:.4f} @ ${price:.4f} "
                f"| SL: ${stop} | TP: ${target} "
                f"| Conf: {signal_result.confidence}% | {signal_result.conditions_met}/5 conditions"
            )

    def _execute_sell(self, symbol: str, asset_type: str, broker,
                      position: dict, price: float,
                      portfolio_value: float, reason: str):
        quantity   = position["quantity"]
        entry      = position.get("avg_price", price)
        pnl        = (price - entry) * quantity

        success, order_id = broker.place_market_order(symbol, "SELL", quantity)
        status = "FILLED" if success else "REJECTED"

        log_trade(symbol, asset_type, "SELL", quantity, price,
                  TRADING_MODE, status, order_id, pnl=pnl,
                  notes=reason)

        if success:
            upsert_position(symbol, asset_type, 0, 0)
            if pnl < 0:
                self._daily_losses[symbol] = self._daily_losses.get(symbol, 0) + 1
                count = self._daily_losses[symbol]
                logger.info(f"[{symbol}] Daily loss count: {count}/2")

            pnl_str = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
            logger.info(
                f"{'OK:' if pnl >= 0 else '--'} [{symbol}] SELL @ ${price:.4f} "
                f"| PnL: {pnl_str} | Reason: {reason}"
            )


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    setup_logging()
    init_db()
    bot = TradingBot()
    bot.run()
