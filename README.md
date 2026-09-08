# MAYA Trading Bot

An open-source paper trading bot with a live signal dashboard. Built for learning — no brokerage account or paid data required.

Uses **Yahoo Finance** (free) for price data. All trades are simulated.

![Python](https://img.shields.io/badge/Python-3.9+-blue)
![License](https://img.shields.io/badge/License-MIT-green)
![Mode](https://img.shields.io/badge/Mode-Paper%20Only-orange)

---

## What it does

MAYA scans a watchlist of stocks every 60 seconds, computes a confidence score using 3 indicators, and places simulated trades when all 5 conditions align.

**The 5 conditions (all must be met to buy):**

| Condition | What it checks |
|---|---|
| Regime | Market must be trending up, not ranging or falling |
| Confidence | Combined indicator score ≥ 65% |
| EMA crossover | Fast (9-bar) EMA above slow (21-bar) EMA |
| RSI zone | RSI between 30–70 (not overbought or oversold) |
| Daily limit | Max trades per day not reached |

The dashboard shows exactly which conditions are met for each stock in real time — making it easy to understand why the bot buys or holds.

---

## Quick start

**1 — Clone:**
```bash
git clone https://github.com/YOUR_USERNAME/maya-trader.git
cd maya-trader
```

**2 — Install:**
```bash
pip install -r requirements.txt
```

**3 — Configure:**
```bash
cp config.example.py config.py
# Edit config.py — set your watchlist and risk settings
```

**4 — Run:**
```bash
python server.py
```

**5 — Open dashboard:**
```
http://localhost:5000
```

Click **Start Bot** and watch the signals page to see conditions being evaluated in real time.

---

## Configuration

All settings live in `config.py`:

| Setting | Default | What it does |
|---|---|---|
| `STOCK_SYMBOLS` | 10 tech stocks | The watchlist to scan |
| `candle_period` | `15m` | How often to check signals |
| `min_confidence` | `65` | Signal strength threshold |
| `stop_loss_pct` | `0.5%` | Max loss per trade |
| `take_profit_pct` | `1.0%` | Target profit per trade |
| `max_open_positions` | `5` | Max simultaneous trades |
| `max_daily_trades` | `5` | Hard daily trade cap |

---

## How the strategy works

**Confidence score** — each indicator contributes points:

```
EMA crossover score    ×  40 points
RSI zone score         ×  35 points
MACD momentum score    ×  25 points
──────────────────────────────────
Total                  =  0–100 confidence
```

A score above 65 (configurable) triggers a BUY signal — if the other 4 conditions are also met.

**Regime detection** — MAYA uses a separate regime detector that classifies the current market as TRENDING_UP, RANGING, HIGH_VOLATILITY or TRENDING_DOWN. Trades are only taken in TRENDING_UP and LOW_VOLATILITY conditions to avoid choppy markets.

---

## Project files

```
maya-trader/
├── bot.py              # Main trading loop
├── strategy.py         # Signal computation + condition checklist
├── broker_yahoo.py     # Yahoo Finance data + paper order execution
├── database.py         # SQLite trade logging
├── server.py           # Flask dashboard server
├── dashboard.html      # Frontend dashboard
├── regime_detector.py  # Market regime classification
├── config.example.py   # Settings template
├── requirements.txt    # Python dependencies
└── README.md
```

---

## Dashboard pages

- **Dashboard** — P&L, win rate, open positions, recent trades
- **Signals** — live condition checklist for each stock showing exactly why the bot buys or holds
- **Positions** — open trades with entry price, stop loss and take profit
- **Trade Log** — full history of all simulated trades with P&L
- **Bot Log** — real-time log output
- **Settings** — adjust confidence, candle timeframe and daily limits

---

## Disclaimer

MAYA is for **educational purposes only**. It is a paper trading simulator — no real money is involved. Past performance on simulated trades does not predict real trading results. Always understand the risks before trading with real money.

---

## License

MIT — free to use, modify and share.
