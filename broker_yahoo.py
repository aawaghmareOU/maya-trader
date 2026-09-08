"""
MAYA Trading Bot — broker_yahoo.py
====================================
Free data broker using Yahoo Finance.
No brokerage account required.
All trades are paper (simulated) only.

Data: yfinance (15-20 min delayed, free)
Orders: simulated locally, no real money
"""

import logging
import random
from datetime import datetime
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

# Candle period → yfinance interval + period mapping
_CP_MAP = {
    "1m":  ("1m",  "1d"),
    "5m":  ("5m",  "5d"),
    "15m": ("15m", "5d"),
    "30m": ("30m", "1mo"),
    "1h":  ("1h",  "1mo"),
    "1d":  ("1d",  "6mo"),
}


class YahooBroker:
    """
    Paper trading broker using Yahoo Finance for price data.
    All orders are simulated — no real money involved.
    """

    def __init__(self):
        self.connected = True
        self._equity   = 50_000.0   # starting paper capital
        logger.info("OK: Yahoo Finance paper broker initialised ($50,000 virtual capital)")

    def connect(self):
        pass

    def disconnect(self):
        pass

    def get_portfolio_value(self) -> float:
        return self._equity

    def get_price(self, symbol: str) -> Optional[float]:
        """Get latest price from Yahoo Finance."""
        try:
            import yfinance as yf
            ticker = yf.Ticker(symbol)
            price  = ticker.fast_info.get("last_price") or ticker.fast_info.get("regularMarketPrice")
            if price and price > 0:
                return float(price)
        except Exception as e:
            logger.warning(f"[{symbol}] Price fetch failed: {e}")
        return None

    def get_historical_closes(self, symbol: str, bars: int = 100) -> List[float]:
        """
        Fetch historical closing prices for indicator calculation.
        Uses candle period from config if available, defaults to 5m.
        """
        try:
            import yfinance as yf

            # Read candle period from config
            try:
                from config import CANDLE_PERIOD as _cp
            except ImportError:
                _cp = "5m"
            yf_interval, yf_period = _CP_MAP.get(_cp, ("5m", "5d"))

            ticker = yf.Ticker(symbol)
            df = ticker.history(
                period=yf_period,
                interval=yf_interval,
                auto_adjust=False,
                prepost=False,
            )

            if df.empty:
                raise ValueError(f"No data returned for {symbol}")

            # Fix MultiIndex columns
            if hasattr(df.columns, "levels"):
                df.columns = df.columns.get_level_values(0)

            closes = [float(x) for x in df["Close"].dropna().values]
            if not closes:
                raise ValueError(f"Empty closes for {symbol}")

            # Sanity filter — skip candles with >8% move (data glitch)
            clean   = [closes[0]]
            glitches = 0
            for i in range(1, len(closes)):
                prev, curr = clean[-1], closes[i]
                if prev > 0 and abs(curr - prev) / prev > 0.08:
                    glitches += 1
                    clean.append(prev)   # repeat previous price
                else:
                    clean.append(curr)

            if glitches > 0:
                logger.warning(f"[{symbol}] Filtered {glitches} bad candle(s)")

            closes = clean
            logger.info(f"[{symbol}] Price: ${closes[-1]:.2f} ({len(closes)} bars, {yf_interval})")
            return closes[-bars:]

        except Exception as e:
            logger.warning(f"[{symbol}] History fetch failed: {e}")
            return []

    def place_market_order(self, symbol: str, side: str,
                           quantity: float) -> Tuple[bool, str]:
        """
        Simulate a market order. No real orders placed.
        Returns (success, order_id).
        """
        order_id = f"PAPER-{datetime.utcnow().strftime('%H%M%S%f')}"
        price    = self.get_price(symbol) or 100.0
        cost     = price * quantity

        if side == "BUY":
            self._equity -= cost
        elif side == "SELL":
            self._equity += cost

        logger.info(f"[PAPER] {side} {quantity:.4f} {symbol} @ ${price:.2f} | ID: {order_id}")
        return True, order_id

    def get_open_positions(self) -> List[dict]:
        """Returns empty list — positions tracked in database."""
        return []


def get_stock_broker() -> YahooBroker:
    """Factory function — always returns Yahoo paper broker."""
    return YahooBroker()


def get_crypto_broker():
    """Crypto not supported in Yahoo-only mode."""
    logger.info("Crypto disabled in Yahoo-only mode")
    return None
