"""
MAYA Ladder Trading — Regime Detector  v1
==========================================
Classifies each symbol into one of 5 market regimes every scan.
Rule-based, fully transparent — no ML library required.

Regimes:
  TRENDING_UP    — EMA bullish crossover, positive slope, RSI 45-65
  TRENDING_DOWN  — EMA bearish, negative slope, RSI 35-55
  RANGING        — EMAs close together, price oscillating, low ATR
  HIGH_VOLATILITY— ATR > 2x 20-period average — chaotic, wider stops needed
  LOW_VOLATILITY — ATR < 0.5x average — compression, breakout likely soon

Output per symbol:
  {
    "regime":      "TRENDING_UP",
    "confidence":  0.82,
    "tags":        ["TRENDING_UP", "LOW_VOLATILITY"],
    "features":    { trend_strength, volatility_ratio, range_compression, rsi_zone },
    "summary":     "Strong uptrend with compressed volatility — breakout setup forming",
    "action_hint": "Favour BUY signals — raise confidence threshold in ranging markets"
  }

Integration with strategy_v2.py:
  from regime_detector import RegimeDetector
  detector = RegimeDetector()
  regime = detector.detect(closes, symbol)
  adjusted_threshold = detector.adjusted_confidence_threshold(regime)

Used by:
  - bot.py / bot_v2.py  — adjusts BUY threshold per regime
  - server.py           — /api/regime endpoint
  - dashboard           — AI Mode page
"""

import logging
import numpy as np
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional

logger = logging.getLogger("regime_detector")

# ── Regime constants ──────────────────────────────────────────────────────
TRENDING_UP     = "TRENDING_UP"
TRENDING_DOWN   = "TRENDING_DOWN"
RANGING         = "RANGING"
HIGH_VOLATILITY = "HIGH_VOLATILITY"
LOW_VOLATILITY  = "LOW_VOLATILITY"
UNKNOWN         = "UNKNOWN"

ALL_REGIMES = [TRENDING_UP, TRENDING_DOWN, RANGING, HIGH_VOLATILITY, LOW_VOLATILITY]

# Colours for dashboard display
REGIME_COLOURS = {
    TRENDING_UP:     "#00C896",   # green
    TRENDING_DOWN:   "#FF3D6A",   # red
    RANGING:         "#FFB020",   # amber
    HIGH_VOLATILITY: "#FF6B35",   # orange
    LOW_VOLATILITY:  "#4D9FFF",   # blue
    UNKNOWN:         "#8888AA",   # grey
}

# Human-readable labels
REGIME_LABELS = {
    TRENDING_UP:     "Trending Up",
    TRENDING_DOWN:   "Trending Down",
    RANGING:         "Ranging",
    HIGH_VOLATILITY: "High Volatility",
    LOW_VOLATILITY:  "Low Volatility",
    UNKNOWN:         "Unknown",
}

# Adjusted BUY confidence threshold per regime
# In ranging/volatile markets — raise bar. In trending — normal bar.
REGIME_THRESHOLDS = {
    TRENDING_UP:     55,   # normal — good conditions
    TRENDING_DOWN:   80,   # very high — don't fight the trend
    RANGING:         70,   # higher — choppy, fewer entries
    HIGH_VOLATILITY: 75,   # high — risky, need strong signal
    LOW_VOLATILITY:  60,   # slightly above normal — breakout pending
    UNKNOWN:         65,   # default high confidence
}

# Plain English action hints
REGIME_HINTS = {
    TRENDING_UP:     "Favour BUY signals — market trending in your direction",
    TRENDING_DOWN:   "Avoid new BUY entries — wait for trend reversal",
    RANGING:         "Tighter entries needed — price bouncing between levels",
    HIGH_VOLATILITY: "Widen stop-loss — expect larger price swings",
    LOW_VOLATILITY:  "Watch for breakout — volatility compression often precedes big move",
    UNKNOWN:         "Insufficient data — wait for clearer signal",
}


# ── Feature dataclass ─────────────────────────────────────────────────────
@dataclass
class RegimeFeatures:
    """Raw computed features used by the classifier."""
    trend_strength:    float = 0.0   # 0-1, how strong is the EMA trend
    trend_direction:   float = 0.0   # +1 up, -1 down, 0 flat
    ema_gap_pct:       float = 0.0   # % gap between fast and slow EMA
    ema_slope:         float = 0.0   # slope of slow EMA over last 10 bars
    volatility_ratio:  float = 1.0   # current ATR / avg ATR (>1 = high vol)
    range_compression: float = 0.0   # 0-1, how compressed recent range is
    rsi:               float = 50.0  # current RSI
    rsi_zone:          str   = "MID" # OVERSOLD / LOW / MID / HIGH / OVERBOUGHT
    macd_hist:         float = 0.0   # MACD histogram value
    bars_available:    int   = 0     # how many bars were used


# ── Result dataclass ──────────────────────────────────────────────────────
@dataclass
class RegimeResult:
    """Full regime detection result for one symbol."""
    symbol:       str
    regime:       str                         # primary regime
    confidence:   float                       # 0.0 - 1.0
    tags:         List[str] = field(default_factory=list)  # can have multiple
    features:     Optional[RegimeFeatures] = None
    summary:      str   = ""
    action_hint:  str   = ""
    colour:       str   = "#8888AA"
    threshold:    int   = 65                  # adjusted BUY threshold
    confidence_pct: int = 0                   # confidence as 0-100 integer

    def to_dict(self) -> dict:
        return {
            "symbol":       self.symbol,
            "regime":       self.regime,
            "regime_label": REGIME_LABELS.get(self.regime, self.regime),
            "confidence":   round(self.confidence, 3),
            "confidence_pct": self.confidence_pct,
            "tags":         self.tags,
            "summary":      self.summary,
            "action_hint":  self.action_hint,
            "colour":       self.colour,
            "threshold":    self.threshold,
            "features": {
                "trend_strength":    round(self.features.trend_strength, 3),
                "trend_direction":   self.features.trend_direction,
                "ema_gap_pct":       round(self.features.ema_gap_pct, 4),
                "volatility_ratio":  round(self.features.volatility_ratio, 3),
                "range_compression": round(self.features.range_compression, 3),
                "rsi":               round(self.features.rsi, 2),
                "rsi_zone":          self.features.rsi_zone,
                "macd_hist":         round(self.features.macd_hist, 4),
                "bars_available":    self.features.bars_available,
            } if self.features else {}
        }


# ── Indicator helpers ─────────────────────────────────────────────────────
def _ema(prices: np.ndarray, period: int) -> np.ndarray:
    ema = np.zeros_like(prices, dtype=float)
    k = 2 / (period + 1)
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
    ag = np.mean(gains)
    al = np.mean(losses)
    if al == 0:
        return 100.0
    return round(100 - (100 / (1 + ag / al)), 2)


def _atr(prices: np.ndarray, period: int = 14) -> Tuple[float, float]:
    """Returns (current_atr, avg_atr_20) using simplified true range."""
    if len(prices) < period + 1:
        return 0.0, 0.0
    ranges = np.abs(np.diff(prices))
    current_atr = float(np.mean(ranges[-period:]))
    avg_atr     = float(np.mean(ranges[-20:])) if len(ranges) >= 20 else current_atr
    return current_atr, avg_atr


def _ema_slope(ema_series: np.ndarray, lookback: int = 10) -> float:
    """Normalised slope of EMA over last N bars. Positive = upward."""
    if len(ema_series) < lookback + 1:
        return 0.0
    recent = ema_series[-lookback:]
    slope  = (recent[-1] - recent[0]) / (recent[0] + 1e-10)
    return float(slope)


def _rsi_zone(rsi: float) -> str:
    if rsi < 30:   return "OVERSOLD"
    if rsi < 40:   return "LOW"
    if rsi < 60:   return "MID"
    if rsi < 70:   return "HIGH"
    return "OVERBOUGHT"


def _macd_histogram(prices: np.ndarray) -> float:
    if len(prices) < 35:
        return 0.0
    ef = _ema(prices, 12)
    es = _ema(prices, 26)
    ml = ef - es
    if len(ml[25:]) < 9:
        return 0.0
    sig = _ema(ml[25:], 9)
    return float(ml[-1] - sig[-1])


# ── Feature extraction ────────────────────────────────────────────────────
def extract_features(closes: List[float]) -> RegimeFeatures:
    """Turn a closes array into a RegimeFeatures object."""
    prices = np.array(closes, dtype=float)
    n      = len(prices)

    if n < 30:
        return RegimeFeatures(bars_available=n)

    # EMA
    fast_ema = _ema(prices, 9)
    slow_ema = _ema(prices, 21)
    fn, sn   = float(fast_ema[-1]), float(slow_ema[-1])
    fp, sp   = float(fast_ema[-2]), float(slow_ema[-2])

    # Trend direction: +1 up, -1 down, 0 flat
    gap_now  = fn - sn
    gap_prev = fp - sp
    if fn > sn:
        direction = 1.0
    elif fn < sn:
        direction = -1.0
    else:
        direction = 0.0

    # Trend strength: how wide is the EMA gap relative to price
    ema_gap_pct    = abs(gap_now) / (sn + 1e-10)
    trend_strength = min(1.0, ema_gap_pct * 100)   # normalise — 1% gap = strength 1.0

    # EMA slope
    slope = _ema_slope(slow_ema)

    # ATR — volatility
    current_atr, avg_atr = _atr(prices)
    vol_ratio = current_atr / (avg_atr + 1e-10)

    # Range compression — how tight are the last 10 bars vs last 50
    if n >= 50:
        recent_range = float(np.max(prices[-10:]) - np.min(prices[-10:]))
        base_range   = float(np.max(prices[-50:]) - np.min(prices[-50:]))
        compression  = 1.0 - (recent_range / (base_range + 1e-10))
        compression  = max(0.0, min(1.0, compression))
    else:
        compression = 0.0

    # RSI
    rsi = _rsi(prices)

    # MACD
    macd_h = _macd_histogram(prices)

    return RegimeFeatures(
        trend_strength    = trend_strength,
        trend_direction   = direction,
        ema_gap_pct       = ema_gap_pct,
        ema_slope         = slope,
        volatility_ratio  = vol_ratio,
        range_compression = compression,
        rsi               = rsi,
        rsi_zone          = _rsi_zone(rsi),
        macd_hist         = macd_h,
        bars_available    = n,
    )


# ── Regime classifier ─────────────────────────────────────────────────────
def classify(f: RegimeFeatures) -> Tuple[str, float, List[str]]:
    """
    Rule-based classifier. Returns (primary_regime, confidence, all_tags).

    Rules are ordered by priority:
    1. Volatility check first (overrides everything)
    2. Trend check
    3. Ranging check
    """
    tags       = []
    scores     = {r: 0.0 for r in ALL_REGIMES}

    # ── Volatility rules ──────────────────────────────────────────────────
    if f.volatility_ratio > 2.0:
        scores[HIGH_VOLATILITY] += 1.0
        tags.append(HIGH_VOLATILITY)
    elif f.volatility_ratio > 1.5:
        scores[HIGH_VOLATILITY] += 0.6
    elif f.volatility_ratio < 0.5:
        scores[LOW_VOLATILITY] += 1.0
        tags.append(LOW_VOLATILITY)
    elif f.volatility_ratio < 0.75:
        scores[LOW_VOLATILITY] += 0.5

    # ── Trend rules ───────────────────────────────────────────────────────
    if f.trend_direction == 1.0:
        # EMA bullish
        trend_conf = min(1.0, f.trend_strength * 5 + 0.3)
        if f.ema_slope > 0.001 and f.rsi_zone in ("MID", "HIGH"):
            scores[TRENDING_UP] += trend_conf
            tags.append(TRENDING_UP)
        elif f.ema_slope > 0:
            scores[TRENDING_UP] += trend_conf * 0.6

    elif f.trend_direction == -1.0:
        # EMA bearish
        trend_conf = min(1.0, f.trend_strength * 5 + 0.3)
        if f.ema_slope < -0.001 and f.rsi_zone in ("MID", "LOW"):
            scores[TRENDING_DOWN] += trend_conf
            tags.append(TRENDING_DOWN)
        elif f.ema_slope < 0:
            scores[TRENDING_DOWN] += trend_conf * 0.6

    # ── Ranging rules ────────────────────────────────────────────────────
    if f.trend_strength < 0.1 and f.range_compression > 0.4:
        scores[RANGING] += 0.8
        tags.append(RANGING)
    elif f.trend_strength < 0.2 and f.range_compression > 0.2:
        scores[RANGING] += 0.4

    # RSI in mid zone supports ranging
    if f.rsi_zone == "MID" and abs(f.trend_direction) < 0.5:
        scores[RANGING] += 0.2

    # ── Pick primary regime ───────────────────────────────────────────────
    if max(scores.values()) < 0.1:
        return UNKNOWN, 0.3, [UNKNOWN]

    primary    = max(scores, key=scores.get)
    raw_conf   = scores[primary]
    confidence = min(0.99, max(0.3, raw_conf))

    if not tags:
        tags = [primary]

    return primary, confidence, list(set(tags))


# ── Summary generator ─────────────────────────────────────────────────────
def generate_summary(symbol: str, regime: str,
                     f: RegimeFeatures, confidence: float) -> str:
    """Generate a plain English 1-2 sentence market summary."""
    conf_word = "strongly" if confidence > 0.75 else \
                "moderately" if confidence > 0.5 else "weakly"

    rsi_desc = {
        "OVERSOLD":   "deeply oversold (RSI {:.0f}) — possible reversal zone",
        "LOW":        "in dip territory (RSI {:.0f}) — potential entry zone",
        "MID":        "neutral (RSI {:.0f})",
        "HIGH":       "elevated (RSI {:.0f}) — momentum strong",
        "OVERBOUGHT": "overbought (RSI {:.0f}) — avoid new entries",
    }.get(f.rsi_zone, "neutral (RSI {:.0f})").format(f.rsi)

    vol_desc = ""
    if f.volatility_ratio > 2.0:
        vol_desc = " Volatility is elevated — expect wider price swings."
    elif f.volatility_ratio < 0.5:
        vol_desc = " Volatility is compressed — a breakout may be near."

    summaries = {
        TRENDING_UP: (
            f"{symbol} is {conf_word} trending upward with RSI {rsi_desc}."
            f"{vol_desc}"
        ),
        TRENDING_DOWN: (
            f"{symbol} is {conf_word} in a downtrend with RSI {rsi_desc}. "
            f"Avoid new long entries until trend reverses.{vol_desc}"
        ),
        RANGING: (
            f"{symbol} is ranging — price oscillating between levels. "
            f"RSI {rsi_desc}. Require higher confidence before entering.{vol_desc}"
        ),
        HIGH_VOLATILITY: (
            f"{symbol} is in a high-volatility phase — ATR is "
            f"{f.volatility_ratio:.1f}x the 20-period average. "
            f"RSI {rsi_desc}. Widen stop-losses or reduce position size."
        ),
        LOW_VOLATILITY: (
            f"{symbol} is in a low-volatility compression phase. "
            f"RSI {rsi_desc}. Watch for a breakout — "
            f"tight ranges often precede significant moves."
        ),
        UNKNOWN: (
            f"{symbol} — insufficient data to classify market regime. "
            f"RSI {rsi_desc}. Wait for clearer conditions."
        ),
    }
    return summaries.get(regime, f"{symbol} — {REGIME_LABELS.get(regime, regime)}")


# ── Main detector class ───────────────────────────────────────────────────
class RegimeDetector:
    """
    Main interface. Call detect() for each symbol every scan.

    Example:
        detector = RegimeDetector()
        result = detector.detect(closes, "NVDA")
        print(result.regime)           # "TRENDING_UP"
        print(result.confidence_pct)   # 82
        print(result.summary)          # "NVDA is strongly trending upward..."
        print(result.threshold)        # 55  (adjusted BUY threshold)
    """

    def detect(self, closes: List[float], symbol: str = "") -> RegimeResult:
        """Detect market regime from a closes array."""
        if len(closes) < 30:
            return RegimeResult(
                symbol      = symbol,
                regime      = UNKNOWN,
                confidence  = 0.3,
                tags        = [UNKNOWN],
                features    = RegimeFeatures(bars_available=len(closes)),
                summary     = f"{symbol} — not enough data ({len(closes)} bars, need 30+)",
                action_hint = REGIME_HINTS[UNKNOWN],
                colour      = REGIME_COLOURS[UNKNOWN],
                threshold   = REGIME_THRESHOLDS[UNKNOWN],
                confidence_pct = 30,
            )

        features   = extract_features(closes)
        regime, confidence, tags = classify(features)
        summary    = generate_summary(symbol, regime, features, confidence)

        result = RegimeResult(
            symbol         = symbol,
            regime         = regime,
            confidence     = confidence,
            confidence_pct = int(confidence * 100),
            tags           = tags,
            features       = features,
            summary        = summary,
            action_hint    = REGIME_HINTS.get(regime, ""),
            colour         = REGIME_COLOURS.get(regime, REGIME_COLOURS[UNKNOWN]),
            threshold      = REGIME_THRESHOLDS.get(regime, 65),
        )

        logger.info(
            f"[Regime] [{symbol}] {regime} "
            f"conf={result.confidence_pct}% "
            f"RSI={features.rsi:.1f} "
            f"vol_ratio={features.volatility_ratio:.2f} "
            f"trend_str={features.trend_strength:.3f}"
        )

        return result

    def detect_all(self, symbols_closes: Dict[str, List[float]]) -> Dict[str, RegimeResult]:
        """Detect regime for multiple symbols at once."""
        return {sym: self.detect(closes, sym)
                for sym, closes in symbols_closes.items()}

    def adjusted_confidence_threshold(self, result: RegimeResult) -> int:
        """
        Returns the recommended BUY confidence threshold for this regime.
        Use this in strategy_v2.py instead of the hardcoded 55.

        Example in bot.py:
            regime = detector.detect(closes, symbol)
            threshold = detector.adjusted_confidence_threshold(regime)
            if confidence >= threshold and fast_ema > slow_ema:
                signal = "BUY"
        """
        return result.threshold

    def market_summary(self, results: Dict[str, RegimeResult]) -> dict:
        """
        Aggregate regime summary across all symbols.
        Returns counts and overall market mood.
        """
        counts = {r: 0 for r in ALL_REGIMES + [UNKNOWN]}
        for r in results.values():
            counts[r.regime] = counts.get(r.regime, 0) + 1

        # Overall mood
        if counts[TRENDING_UP] > counts[TRENDING_DOWN] + 1:
            mood = "Bullish"
        elif counts[TRENDING_DOWN] > counts[TRENDING_UP] + 1:
            mood = "Bearish"
        elif counts[HIGH_VOLATILITY] >= 2:
            mood = "Volatile"
        elif counts[RANGING] >= 3:
            mood = "Ranging"
        else:
            mood = "Mixed"

        avg_conf = sum(r.confidence for r in results.values()) / max(len(results), 1)

        return {
            "mood":          mood,
            "counts":        counts,
            "avg_confidence": round(avg_conf, 2),
            "avg_threshold":  int(sum(r.threshold for r in results.values()) / max(len(results), 1)),
            "symbols_count":  len(results),
        }


# ── Singleton ─────────────────────────────────────────────────────────────
_detector = RegimeDetector()

def detect_regime(closes: List[float], symbol: str = "") -> RegimeResult:
    """Module-level convenience function."""
    return _detector.detect(closes, symbol)


# ── Standalone test ───────────────────────────────────────────────────────
if __name__ == "__main__":
    import random
    random.seed(42)

    def make_trend(base, n, drift=0.001, vol=0.003):
        p = [base]
        for _ in range(n - 1):
            p.append(p[-1] * (1 + random.gauss(drift, vol)))
        return p

    def make_range(base, n, vol=0.002):
        p = [base]
        for _ in range(n - 1):
            p.append(base + random.gauss(0, base * vol))
        return p

    detector = RegimeDetector()

    test_cases = [
        ("NVDA_TREND_UP",   make_trend(200, 100, drift=0.003, vol=0.002)),
        ("ETH_TREND_DOWN",  make_trend(2300, 100, drift=-0.003, vol=0.004)),
        ("AAPL_RANGING",    make_range(270, 100, vol=0.001)),
        ("BTC_HIGH_VOL",    make_trend(76000, 100, drift=0.0, vol=0.015)),
        ("MSFT_LOW_VOL",    make_range(414, 100, vol=0.0003)),
    ]

    print(f"\n{'='*70}")
    print(f"  MAYA Regime Detector v1 — Test Run")
    print(f"{'='*70}")
    print(f"{'Symbol':<20} {'Regime':<18} {'Conf':>5}  {'RSI':>6}  {'Vol':>5}  {'Threshold'}")
    print(f"{'-'*70}")

    results = {}
    for sym, closes in test_cases:
        r = detector.detect(closes, sym)
        results[sym] = r
        print(f"{sym:<20} {r.regime:<18} {r.confidence_pct:>4}%  "
              f"{r.features.rsi:>6.1f}  {r.features.volatility_ratio:>5.2f}  "
              f"BUY>={r.threshold}")
        print(f"  └─ {r.summary[:75]}")

    summary = detector.market_summary(results)
    print(f"\n{'='*70}")
    print(f"  Market Mood: {summary['mood']}  |  Avg Confidence: {summary['avg_confidence']*100:.0f}%")
    print(f"  Avg BUY Threshold: {summary['avg_threshold']}")
    print(f"{'='*70}\n")
