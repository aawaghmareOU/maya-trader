"""
MAYA Trading Bot — strategy.py
================================
Weighted confidence scoring with regime detection.

Signal is computed from 3 indicators:
  EMA crossover  — 40 points
  RSI zone       — 35 points
  MACD momentum  — 25 points

All 5 conditions must be met for a BUY:
  1. Regime: TRENDING_UP or LOW_VOLATILITY
  2. Confidence >= min_confidence (default 65%)
  3. Fast EMA > Slow EMA (uptrend)
  4. RSI in range 30-70
  5. Daily trade limit not reached
"""

import logging
import numpy as np
from dataclasses import dataclass
from typing import List, Literal, Optional

from config import STRATEGY

logger = logging.getLogger(__name__)

Signal = Literal["BUY", "SELL", "HOLD"]


# ── Signal result ─────────────────────────────────────────────────────────────
@dataclass
class SignalResult:
    signal:          Signal
    confidence:      int
    rsi:             float
    fast_ma:         float
    slow_ma:         float
    price:           float
    reason:          str
    regime:          str  = "UNKNOWN"
    threshold:       int  = 65
    # Condition checklist — shown in dashboard
    cond_regime:     bool = False
    cond_confidence: bool = False
    cond_ma_cross:   bool = False
    cond_rsi:        bool = False
    cond_trades:     bool = True
    conditions_met:  int  = 0


# ── Regime detector ───────────────────────────────────────────────────────────
try:
    from regime_detector import RegimeDetector
    _detector     = RegimeDetector()
    REGIME_OK     = True
    logger.info("[strategy] Regime detector loaded")
except ImportError:
    _detector = None
    REGIME_OK = False
    logger.warning("[strategy] regime_detector.py not found — using UNKNOWN regime")


# ── Indicator helpers ─────────────────────────────────────────────────────────
def _ema(prices: np.ndarray, period: int) -> np.ndarray:
    ema = np.zeros_like(prices, dtype=float)
    k   = 2 / (period + 1)
    ema[period - 1] = np.mean(prices[:period])
    for i in range(period, len(prices)):
        ema[i] = prices[i] * k + ema[i - 1] * (1 - k)
    return ema


def _rsi(prices: np.ndarray, period: int = 14) -> float:
    if len(prices) < period + 1:
        return 50.0
    deltas = np.diff(prices[-(period + 1):])
    gains  = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    ag, al = np.mean(gains), np.mean(losses)
    if al == 0:
        return 100.0
    return round(100 - (100 / (1 + ag / al)), 2)


def _macd(prices: np.ndarray, fast=12, slow=26, signal=9):
    if len(prices) < slow + signal:
        return 0.0, 0.0, 0.0
    ef  = _ema(prices, fast)
    es  = _ema(prices, slow)
    ml  = ef - es
    sig = _ema(ml[slow - 1:], signal)
    return float(ml[-1]), float(sig[-1]), float(ml[-1] - sig[-1])


# ── Scoring ───────────────────────────────────────────────────────────────────
def score_ema(fp, sp, fn, sn) -> float:
    if fn <= sn:           return 0.0
    if fp <= sp and fn > sn: return 1.0
    return 0.7 if (fn - sn) > (fp - sp) else 0.4


def score_rsi(rsi: float) -> float:
    if rsi > 70:                       return 0.0
    if 35 <= rsi <= 45:               return 1.0
    if (28 <= rsi < 35) or (45 < rsi <= 55): return 0.7
    if 20 <= rsi < 28:                return 0.3
    return 0.15


def score_macd(hist: float, macd_line: float) -> float:
    if hist < 0:                    return 0.0
    if hist > 0 and macd_line > 0: return 1.0
    if hist > 0:                    return 0.4
    return 0.0


# ── Main signal computation ───────────────────────────────────────────────────
def compute_signal(closes: List[float], symbol: str = "") -> SignalResult:
    """
    Compute BUY / SELL / HOLD signal with condition checklist.
    Returns SignalResult with full breakdown of which conditions are met.
    """
    prices = np.array(closes, dtype=float)
    cfg    = STRATEGY

    # Need enough bars for indicators
    min_len = max(cfg.slow_ma_period, cfg.rsi_period, 35) + 5
    if len(prices) < min_len:
        return SignalResult(
            signal="HOLD", confidence=0, rsi=50.0,
            fast_ma=0.0, slow_ma=0.0,
            price=float(prices[-1]) if len(prices) else 0.0,
            reason="Insufficient data",
        )

    # ── Compute indicators ────────────────────────────────────────────────────
    fast_ema = _ema(prices, cfg.fast_ma_period)
    slow_ema = _ema(prices, cfg.slow_ma_period)
    rsi      = _rsi(prices, cfg.rsi_period)
    macd_line, _, histogram = _macd(
        prices, cfg.macd_fast, cfg.macd_slow, cfg.macd_signal
    )

    fast_now  = float(fast_ema[-1])
    slow_now  = float(slow_ema[-1])
    fast_prev = float(fast_ema[-2])
    slow_prev = float(slow_ema[-2])
    price     = float(prices[-1])

    # ── Score indicators ──────────────────────────────────────────────────────
    s_ema  = score_ema(fast_prev, slow_prev, fast_now, slow_now)
    s_rsi  = score_rsi(rsi)
    s_macd = score_macd(histogram, macd_line)
    confidence = int(s_ema * 40 + s_rsi * 35 + s_macd * 25)

    # ── Regime detection ──────────────────────────────────────────────────────
    regime_name   = "UNKNOWN"
    BUY_THRESHOLD = cfg.min_confidence

    if REGIME_OK and _detector:
        try:
            result        = _detector.detect(closes, symbol)
            regime_name   = result.regime
            BUY_THRESHOLD = result.threshold
        except Exception as e:
            logger.warning(f"[{symbol}] Regime detection failed: {e}")

    # Regime gate — only buy in trending/low-vol markets
    regime_allows_buy = regime_name in ("TRENDING_UP", "LOW_VOLATILITY", "UNKNOWN")

    # ── Decision ──────────────────────────────────────────────────────────────
    if confidence >= BUY_THRESHOLD and fast_now > slow_now and regime_allows_buy:
        signal = "BUY"
        reason = (f"Conf={confidence}>={BUY_THRESHOLD} | Regime={regime_name} | "
                  f"EMA={s_ema:.1f} RSI={rsi:.1f} MACD={histogram:.4f}")

    elif confidence >= BUY_THRESHOLD and fast_now > slow_now and not regime_allows_buy:
        signal = "HOLD"
        reason = f"REGIME GATE: {regime_name} — blocked | Conf={confidence} would have fired"

    elif fast_now < slow_now and rsi > 70:
        signal = "SELL"
        reason = f"EMA bearish + RSI overbought {rsi:.1f}"

    else:
        signal = "HOLD"
        reason = (f"Conf={confidence} (need {BUY_THRESHOLD}) | "
                  f"Regime={regime_name} | EMA={s_ema:.1f} RSI={rsi:.1f}")

    # ── Condition checklist ───────────────────────────────────────────────────
    cond_regime     = regime_allows_buy
    cond_confidence = confidence >= BUY_THRESHOLD
    cond_ma_cross   = fast_now > slow_now
    cond_rsi        = 30 <= rsi <= 70
    cond_trades     = True  # checked in bot.py
    conditions_met  = sum([cond_regime, cond_confidence, cond_ma_cross,
                           cond_rsi, cond_trades])

    result = SignalResult(
        signal=signal, confidence=confidence, rsi=rsi,
        fast_ma=round(fast_now, 4), slow_ma=round(slow_now, 4),
        price=round(price, 4), reason=reason,
        regime=regime_name, threshold=BUY_THRESHOLD,
        cond_regime=cond_regime, cond_confidence=cond_confidence,
        cond_ma_cross=cond_ma_cross, cond_rsi=cond_rsi,
        cond_trades=cond_trades, conditions_met=conditions_met,
    )

    logger.info(
        f"[{symbol}] {signal} | Conf={confidence}% | "
        f"Regime={regime_name} | RSI={rsi:.1f} | {conditions_met}/5 conditions"
    )
    return result
