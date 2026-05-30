# Alpha Scanner — Systematic Swing Trading Bot

A fully automated swing trading system that backtests 7 quantitative strategies across 735 US equities, ranks every strategy-ticker combination by historical robustness, generates daily entry/exit signals on the top-ranked combinations, and executes paper (or live) trades via Alpaca with automatic stop-loss protection and P&L tracking.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Architecture & File Structure](#2-architecture--file-structure)
3. [Data Pipeline](#3-data-pipeline)
4. [Backtesting Engine](#4-backtesting-engine)
5. [The 7 Strategies](#5-the-7-strategies)
6. [The Robustness Score](#6-the-robustness-score)
7. [Walk-Forward Validation](#7-walk-forward-validation)
8. [Daily Signal Generation](#8-daily-signal-generation)
9. [Trade Execution](#9-trade-execution)
10. [P&L Tracker](#10-pl-tracker)
11. [Automation](#11-automation)
12. [Performance Benchmarks](#12-performance-benchmarks)
13. [Risk Management](#13-risk-management)
14. [Recession & Bear Market Behaviour](#14-recession--bear-market-behaviour)
15. [Going Live](#15-going-live)
16. [Roadmap](#16-roadmap)

---

## 1. System Overview

The premise of this system is simple: **not every strategy works on every stock**. RSI mean reversion might work exceptionally well on a pharmaceutical company that oscillates in a range, but terribly on a high-momentum tech stock. Rather than picking one strategy and applying it universally, this system:

1. Tests every strategy against every stock over 25 years of historical data
2. Scores each combination by how _robustly_ it performed — not just raw return, but consistency, risk-adjustment, and repeatability
3. Builds a watchlist of only the top-ranked combinations
4. Each morning, checks that watchlist for live entry/exit signals
5. Executes trades automatically with built-in risk management

The result is a system where **every trade has a 25-year historical precedent** supporting it, including the 2000 dot-com crash, the 2008 financial crisis, and multiple bear markets.

---

## 2. Architecture & File Structure

```
alpha-scanner-core/
│
├── data.py           # Data pipeline — WRDS/CRSP history + yfinance daily top-up
├── main.py           # Backtesting engine — runs all strategies on all tickers
├── strategies.py     # Strategy definitions — 7 quantitative strategies
├── validate.py       # Rolling walk-forward validation — 4 windows, finds real survivors
├── signals.py        # Daily signal generator — uses validated watchlist (29 survivors)
├── bot.py            # Trade executor — places orders via Alpaca API
├── tracker.py        # P&L tracker — detects exits, computes win rate/profit factor
├── run_daily.sh      # Daily runner — orchestrates all 4 steps each morning
│
├── datasets/
│   ├── cache/                  # 735 individual ticker price CSVs (AAPL_prices.csv, etc.)
│   ├── scan_results.csv        # Ranked backtest results — 5,048 strategy-ticker combos
│   ├── validation_results.csv  # Aggregated walk-forward survivors — source of truth for live trading
│   ├── validation_raw.csv      # Per-window raw results — for inspection and debugging
│   ├── trade_log.csv           # Live trade log — every entry and exit with P&L
│   └── daily_YYYY-MM-DD.log   # Daily run logs
│
├── .env              # API credentials (Alpaca, WRDS) — never commit this
├── requirements.txt  # Python dependencies
└── venv/             # Python virtual environment
```

### How the pieces connect

```
data.py  ──────────────→  datasets/cache/  (735 price CSVs)
                                │
main.py  ──────────────────────→  datasets/scan_results.csv  (ranked combos)
                                              │
validate.py  ─────────────────────────────────→  datasets/validation_results.csv  (29 survivors)
                                                                │
signals.py  ────────────────────────────────────────────────────→  BUY / SELL / HOLD signals
                                                                              │
bot.py  ──────────────────────────────────────────────────────────────────────→  Alpaca orders
                                                                                        │
tracker.py  ────────────────────────────────────────────────────────────────────────────→  trade_log.csv
```

---

## 3. Data Pipeline

### Source 1 — WRDS / CRSP (Historical backbone)

**What it is:** The Center for Research in Security Prices (CRSP) is the gold-standard academic database for US equity price data, maintained by Wharton. It's the same dataset used by institutional researchers and quantitative hedge funds.

**Why CRSP over yfinance for history:**

- Properly adjusted for splits, dividends, and corporate actions going back decades
- Survivorship-bias aware — includes delisted stocks
- Institutional quality, no missing data or adjustment errors

**What we pull:**

- 735 US equities across NYSE, NASDAQ, and AMEX
- Daily adjusted close prices from **January 2000 → December 2024**
- ~6,300 trading days per ticker = ~25 years of history
- Each ticker stored as an individual CSV: `datasets/cache/AAPL_prices.csv`

**The CRSP query:**

```sql
SELECT permno, date,
       abs(prc) / NULLIF(cfacpr, 0) AS close
FROM   crsp.dsf
WHERE  permno IN (...)
  AND  date   >= '2000-01-01'
  AND  prc    IS NOT NULL
  AND  cfacpr  > 0
ORDER  BY permno, date
```

- `prc`: raw price (negative means no trades that day, just a quote — `abs()` handles this)
- `cfacpr`: cumulative adjustment factor for splits and dividends
- `abs(prc) / cfacpr`: fully adjusted close price

**Connection:** WRDS PostgreSQL database at `wrds-pgdata.wharton.upenn.edu:9737`, authenticated via WRDS academic credentials.

---

### Source 2 — yfinance (Daily top-up)

Since CRSP data ends at December 2024, yfinance fills the gap from January 2025 to today. Not all 735 tickers have data back to 2000 — newer listings contribute whatever history is available, and the code handles shorter series gracefully. Every morning before signals are generated, `data.py --topup` runs and:

1. Reads the last date in each ticker's cached CSV
2. Fetches only the missing days from yfinance (e.g., if cache ends Apr 28, fetches Apr 29)
3. Merges new rows into the existing CSV, deduplicating on date
4. Moves on — takes ~0.05 seconds per ticker with a small sleep to avoid rate limiting

**Result:** By 9:35am every trading day, all 735 tickers have prices through yesterday's close (the most recent available bar).

---

### The 735-Ticker Universe

The universe is all tickers that existed in CRSP at the time of the initial download. This covers the broad US equity market — not just the S&P 500, but also mid-cap and small-cap names across all major exchanges. Tickers are static (the universe doesn't automatically update with new IPOs) unless a full CRSP refresh is run.

Some tickers in the cache are now delisted (SIVB — Silicon Valley Bank, PXD — acquired by Exxon, SQ — rebranded). These throw yfinance warnings during top-up but are automatically skipped. They still contribute their historical data to the backtest.

---

## 4. Backtesting Engine

**File:** `main.py`

### What it does

`main.py` runs every strategy against every cached ticker and produces a ranked leaderboard of all strategy-ticker combinations. This is the brain of the system — it answers the question: _"historically, which strategy worked best on which stock?"_

### The process

```
For each of 735 tickers:
    Load close price series (must have ≥ 252 days of history)
    For each of 7 strategies:
        Generate entry/exit signals on the full price history
        Build a vectorbt portfolio simulation
        Extract performance metrics
        Compute robustness score
        Save result if trade_count ≥ 5
```

### Minimum requirements to qualify

- **≥ 252 trading days** of price history (~1 year) — ensures enough data to be meaningful
- **≥ 5 completed trades** — strategies that barely traded are excluded (likely curve-fit to noise)

### Output metrics per combination

| Metric             | Description                                                  |
| ------------------ | ------------------------------------------------------------ |
| `total_return`     | Cumulative % return over 10 years                            |
| `sharpe`           | Risk-adjusted return (return ÷ volatility). Higher = better  |
| `max_drawdown`     | Largest peak-to-trough decline. Lower = better               |
| `win_rate`         | % of closed trades that were profitable                      |
| `trade_count`      | Total number of completed round-trip trades                  |
| `profit_factor`    | Gross profits ÷ gross losses. > 1.0 means profitable overall |
| `robustness_score` | Composite score (see Section 6)                              |

### Scale

- **5,048 qualifying results** from 735 tickers × 7 strategies (some combos filtered out for insufficient trades)
- Results saved to `datasets/scan_results.csv`, sorted by robustness score descending
- Top result: **ADI + BBands(20,2)** with robustness score 423.4, 1192% total return, 87.2% win rate

### When to re-run

`main.py` is not run daily — it's a periodic refresh. Re-run it when:

- New price data has been added (quarterly or annually)
- New strategies are added
- You want to re-rank after adding more tickers to the universe

---

## 5. The 7 Strategies

**File:** `strategies.py`

Each strategy takes a daily close price series and returns two boolean series: `entries` (when to buy) and `exits` (when to sell). All strategies use `vectorbt` for indicator computation.

---

### Strategy 1 — RSI Mean Reversion `RSI(14)`

**Type:** Mean Reversion

**Indicators:** Relative Strength Index (14-day)

**Logic:**

- **BUY** when RSI crosses _below_ 30 (stock is oversold — price has fallen too far, too fast)
- **SELL** when RSI crosses _above_ 70 (stock is overbought — price has risen too far, too fast)

**Premise:** Prices tend to revert to the mean. When a stock is deeply oversold (RSI < 30), institutional buyers step in and push prices back up. This strategy captures that snapback.

**Best on:** Range-bound stocks, defensive sectors, consumer staples. Stocks that don't trend strongly.

**Backtest avg robustness:** 29.71 (2nd highest across all strategies)

---

### Strategy 2 — RSI Mean Reversion `RSI(21)` ❌ Excluded from live trading

**Type:** Mean Reversion

**Logic:** Identical to RSI(14) but uses a 21-day window instead of 14.

**Difference from RSI(14):**

- Slower — takes longer to reach oversold/overbought thresholds
- Fewer signals — only fires on more extreme moves
- More filtered — less noise, but catches fewer opportunities

**When it outperforms RSI(14):** On higher-volatility stocks where RSI(14) generates too many false signals.

**Why it's excluded from live trading:** Walk-forward validation showed RSI(21) produced an average OOS Sharpe of **-0.058** across all 4 rolling windows — the only strategy to lose money out-of-sample. It performs adequately in-sample but fails to generalise. It remains defined in `strategies.py` and included in backtests, but is filtered out of `signals.py` and `bot.py` via the `EXCLUDED_STRATEGIES` list.

---

### Strategy 3 — MACD Crossover `MACD`

**Type:** Momentum / Trend-Following

**Indicators:** MACD line (12-day EMA − 26-day EMA), Signal line (9-day EMA of MACD)

**Logic:**

- **BUY** when MACD line crosses _above_ the signal line (momentum turning bullish)
- **SELL** when MACD line crosses _below_ the signal line (momentum turning bearish)

**Premise:** The crossover between the MACD and signal line indicates a shift in short-term momentum relative to medium-term momentum. When the fast component accelerates above the slow one, a trend is beginning.

**Best on:** Stocks with clear momentum cycles. Technology, growth stocks. Less effective in flat/choppy markets.

**Backtest avg robustness:** 25.69 (3rd highest)

---

### Strategy 4 — Bollinger Bands `BBands(20,2)`

**Type:** Mean Reversion / Volatility

**Indicators:** 20-day SMA (middle band), ±2 standard deviations (upper and lower bands)

**Logic:**

- **BUY** when price closes _below_ the lower band (price is more than 2σ below the 20-day average — statistically extreme)
- **SELL** when price closes _above_ the upper band (price is more than 2σ above the 20-day average)

**Premise:** By definition, only ~5% of price action falls outside the 2σ bands. When it does, it typically snaps back to the mean. This strategy bets on that reversion.

**Best on:** Stocks with stable volatility. Works poorly on stocks that are in strong trending moves (a stock can "walk the bands" during a trend).

**Backtest avg robustness:** 31.54 (highest across all strategies)

---

### Strategy 5 — Moving Average Crossover `MA Cross(50/200)`

**Type:** Trend-Following (Golden Cross / Death Cross)

**Indicators:** 50-day Simple Moving Average, 200-day Simple Moving Average

**Logic:**

- **BUY** when 50-day MA crosses _above_ 200-day MA — the "Golden Cross" — signals a long-term trend turning bullish
- **SELL** when 50-day MA crosses _below_ 200-day MA — the "Death Cross" — signals a long-term trend turning bearish

**Premise:** The Golden/Death Cross is one of the most widely watched technical signals in markets. When shorter-term price action (50-day) decisively breaks above long-term trend (200-day), it signals institutional accumulation and the start of a sustained uptrend.

**Tradeoff:** Very few signals (maybe 2-4 per year per stock) but each signal carries significant conviction. Tends to catch the big multi-month trends.

**Backtest avg robustness:** 5.16 (lowest — few trades means lower composite score even when each trade is good)

---

### Strategy 6 — RSI with Trend Filter `RSI(14)+Trend(200)`

**Type:** Mean Reversion with Trend Confirmation

**Indicators:** RSI (14-day), 200-day Simple Moving Average

**Logic:**

- **BUY** when RSI crosses below 30 **AND** price is above the 200-day MA (uptrend confirmed)
- **SELL** when RSI crosses above 70

**Premise:** RSI mean reversion alone can buy into a downtrending stock — catching a falling knife. Adding the 200-day trend filter ensures you only buy dips within uptrending stocks, not during structural declines.

**Why it matters:** SIVB (Silicon Valley Bank) would have triggered RSI buy signals on the way down in early 2023. The 200-day filter would have blocked those entries entirely.

**Backtest avg robustness:** 21.39 — lower than plain RSI(14) because the trend filter reduces trade count, but higher conviction on each trade.

---

### Strategy 7 — Bollinger Bands + RSI Combo `BBands+RSI`

**Type:** Multi-Indicator Mean Reversion (Dual Confirmation)

**Indicators:** Bollinger Bands (20-day, 2σ), RSI (14-day)

**Logic:**

- **BUY** when price is below lower Bollinger Band **AND** RSI < 30 simultaneously
- **SELL** when price rises above upper Bollinger Band **OR** RSI > 70

**Premise:** Requires two independent indicators to agree before entering. A stock below the lower BB is statistically extreme on a volatility basis. A stock with RSI < 30 is statistically extreme on a momentum basis. When both fire at the same time, the probability of a mean reversion is significantly higher than either signal alone.

**Tradeoff:** Fewest signals of any strategy (both conditions must align), but highest signal quality. Each entry is a high-conviction double-confirmed extreme.

**Backtest avg robustness:** 22.80

---

### Strategy Comparison

| Strategy         | IS Robustness | OOS Sharpe | Live Trading                      |
| ---------------- | ------------- | ---------- | --------------------------------- |
| BBands+RSI       | 22.80         | 1.060      | ✅ Active — best OOS performer    |
| RSI(14)          | 29.71         | 0.864      | ✅ Active                         |
| BBands(20,2)     | 31.54         | 0.694      | ✅ Active                         |
| MACD             | 25.69         | 0.657      | ✅ Active (only 3 window appearances) |
| RSI(21)          | 24.15         | -0.085     | ❌ Excluded — negative OOS Sharpe |
| RSI(14)+Trend    | 21.39         | —          | Not in IS top 50                  |
| MA Cross(50/200) | 5.16          | —          | Not in IS top 50                  |

OOS figures are averages across 9 rolling windows (2006–2024). Walk-forward validation confirmed a key finding: IS ranking order does not reliably predict OOS ranking (rank correlation p > 0.05 across all 9 windows). The live watchlist is sourced from `validation_results.csv` (OOS Sharpe) rather than `scan_results.csv` (IS robustness).

---

## 6. The Robustness Score

**File:** `main.py` — `robustness_score()` function

The robustness score is the single number used to rank every strategy-ticker combination. It's designed to reward strategies that are **consistent, risk-adjusted, accurate, and profitable** — not just lucky.

### Formula

```python
robustness_score = trade_count × sharpe × win_rate × profit_factor
```

With `profit_factor` capped at 10 to prevent outliers from dominating, and `win_rate` expressed as a decimal (0.0–1.0).

### Why each component matters

| Component       | What it penalises                      | What it rewards                                 |
| --------------- | -------------------------------------- | ----------------------------------------------- |
| `trade_count`   | Lucky 1-trade wonders                  | Strategies that have been tested many times     |
| `sharpe`        | High return with high volatility       | Consistent, smooth returns                      |
| `win_rate`      | Strategies that rely on a few big wins | Strategies that are right more often than wrong |
| `profit_factor` | Strategies where losses dwarf winners  | Strategies where wins are bigger than losses    |

### Example: Why a 500% return doesn't automatically win

A strategy that made 500% total return via 3 trades scores:

```
3 × 1.8 × 0.67 × 3.0 = 10.8
```

A strategy with 150% return via 35 trades scores:

```
35 × 1.1 × 0.80 × 2.5 = 77.0
```

The second strategy scores 7x higher despite lower total return, because its edge has been proven 35 times rather than 3.

### Disqualification

Combinations with `trade_count < 5` or `sharpe ≤ 0` receive a score of 0.0 and are excluded from the watchlist entirely.

---

## 7. Walk-Forward Validation

**File:** `validate.py`

### The problem it solves

After backtesting 5,145 strategy-ticker combinations, the top-ranked results are vulnerable to **overfitting** — some combinations score well simply by chance across the 10-year window, not because they have a genuine edge. Testing 5,000+ combinations guarantees some will look great on random noise alone.

The standard fix is **out-of-sample validation**: train on historical data, then test on a separate period the strategy has never seen. If the edge is real, it persists. If it was noise, it collapses.

### Why rolling windows, not a single split

A single train/test split (e.g. 2015–2021 train, 2022–2024 test) has high variance — that one test period could be unusually good or bad by chance. Rolling validation runs **9 independent windows** and averages the results, dramatically reducing the chance of a lucky or unlucky draw. Test years are chosen to cover distinct market regimes, not just recent years.

### The 9 windows

| Window | Train     | Test | Regime                          |
| ------ | --------- | ---- | ------------------------------- |
| 1      | 2000–2005 | 2006 | Post dot-com recovery           |
| 2      | 2000–2007 | 2008 | Global financial crisis         |
| 3      | 2000–2010 | 2011 | Recovery + Euro sovereign crisis|
| 4      | 2000–2014 | 2015 | Oil crash / China slowdown      |
| 5      | 2000–2017 | 2018 | Vol spike / rate fear           |
| 6      | 2000–2020 | 2021 | Post-COVID bull market          |
| 7      | 2000–2021 | 2022 | Rate-hike bear market           |
| 8      | 2000–2022 | 2023 |                                 |
| 9      | 2000–2023 | 2024 |                                 |

Each window independently ranks all combos on the train period, selects the top 50, then tests those 50 on the test year they've never seen. Results are aggregated across all windows a combo appeared in. A combo must appear in at least **3 windows** to be eligible — ensuring it's robust across multiple distinct market regimes, not just recent years.

### What gets measured per combo

- `avg_oos_sharpe` — average Sharpe across all test windows
- `sharpe_decay` — OOS Sharpe ÷ IS Sharpe (1.0 = perfect retention, <0.4 = significant decay)
- `pct_profitable` — fraction of test windows where the combo was profitable
- `windows_tested` — how many IS windows the combo appeared in the top 50
- `active_rate` — fraction of test windows where the strategy actually fired (didn't go silent)

### Survivor criteria

A combo must pass all four filters to make the live watchlist:

```python
oos_sharpe     >= 0.3    # positive risk-adjusted return OOS
sharpe_decay   >= 0.4    # retains at least 40% of IS Sharpe
pct_profitable >= 0.5    # profitable in majority of test windows
windows_tested >= 3      # appeared in IS top 50 in at least 3 windows
```

### Results (as of May 2026)

| Metric                         | Value         |
| ------------------------------ | ------------- |
| Avg IS Sharpe                  | 1.003         |
| Avg OOS Sharpe                 | 0.793         |
| Avg decay ratio                | 0.864         |
| % profitable OOS               | 97.2%         |
| Survivors (passed all filters) | **29 combos** |

Decay > 1.0 on some combos (OOS Sharpe exceeds IS Sharpe) reflects that early training windows include the 2000–2002 dot-com crash, which depresses IS Sharpe. The OOS test years were comparatively cleaner for these strategies — confirming they genuinely generalise rather than overfit.

**Rank correlation** (does IS ranking predict OOS ranking?) — **not significant** across all 9 windows (p > 0.05 in every window). The implication: sorting by OOS Sharpe (from validation) is more meaningful than sorting by IS robustness score.

### Strategy OOS breakdown

| Strategy           | OOS Sharpe | Action                                                   |
| ------------------ | ---------- | -------------------------------------------------------- |
| BBands+RSI         | 1.060      | ✅ Active — best OOS performer (83% profitable)          |
| RSI(14)            | 0.864      | ✅ Active — strong (73% profitable, 68 window tests)     |
| BBands(20,2)       | 0.694      | ✅ Active — solid (75% profitable)                       |
| MACD               | 0.657      | ✅ Active — limited appearances (3 windows only)         |
| RSI(21)            | -0.085     | ❌ **Excluded** — negative OOS Sharpe across all windows |
| RSI(14)+Trend(200) | —          | Not in IS top 50 in any window                           |
| MA Cross(50/200)   | —          | Not in IS top 50 in any window                           |

### How it connects to the live system

`signals.py` and `bot.py` both check for `validation_results.csv` first. If it exists, they use the 29 survivors ranked by OOS Sharpe as the watchlist. If it doesn't exist (e.g. first run before validation), they fall back to `scan_results.csv`. Every morning the log prints which source is active:

```
Watchlist: validated (29 survivors, ranked by OOS Sharpe)
```

### When to re-run

```bash
python3 validate.py   # ~10 minutes
```

Re-run after: adding new strategies, running a full backtest refresh (`main.py`), or quarterly to keep rankings current.

---

## 8. Daily Signal Generation

**File:** `signals.py`

Every morning, `signals.py` loads the validated watchlist and checks each combo for a live signal. It uses `validation_results.csv` (29 walk-forward survivors, ranked by OOS Sharpe) if it exists, falling back to `scan_results.csv` if validation hasn't been run.

### Signal detection

For each combo in the watchlist:

1. Load the ticker's cached price CSV (which was just topped up with today's data)
2. Re-run the strategy's indicator calculations on the full price history
3. Check the **last 3 bars** for a signal:
   - If an entry condition fired in the last 3 days → **BUY**
   - If an exit condition fired in the last 3 days → **SELL**
   - Otherwise → **HOLD**

The 3-bar lookback window ensures a signal from yesterday (or the day before) isn't missed if the cron job was delayed slightly.

### Indicator snapshot

Alongside the signal, a human-readable indicator value is computed for logging:

- RSI strategies: `RSI(14)=28.1 ← oversold`
- BBands strategies: `Price=858.20 below lower BB=865.58`
- MACD: `MACD-Signal=+0.0042`
- MA Cross: `50MA vs 200MA=-2.14%`

### The key insight

The signal generator doesn't ask _"should I trade this stock today?"_ It asks _"does this specific strategy-ticker combination — which has a proven edge both in-sample AND out-of-sample — have a signal right now?"_ The strategy and ticker were pre-selected by the backtest and validated by walk-forward testing. The daily scan just checks whether the entry/exit conditions are currently met.

---

## 8. Trade Execution

**File:** `bot.py`

After signals are generated, `bot.py` connects to Alpaca and executes orders. It applies a final set of filters before placing any trade.

### Pre-trade filters

| Filter              | Rule                                                        | Purpose                               |
| ------------------- | ----------------------------------------------------------- | ------------------------------------- |
| Validated watchlist | OOS Sharpe ≥ 0.3, decay ≥ 0.4, ≥ 3 windows                  | Only trade walk-forward proven combos |
| Excluded strategies | RSI(21) always blocked                                      | Negative OOS Sharpe confirmed         |
| Max positions       | Never hold > 10 stocks                                      | Concentration limit                   |
| Deduplication       | One trade per ticker regardless of how many strategies fire | Avoid doubling up                     |
| Buying power        | Skip if account can't cover $10,000                         | Prevent over-leverage                 |

### Order type — OTO (One-Triggers-Other)

Every BUY is placed as an OTO bracket order:

```
Market BUY at current ask/bid midpoint
    └── Stop Loss at entry_price × 0.95 (5% below entry)
```

The stop loss lives on Alpaca's servers. If the stock drops 5% intraday — even if the Mac is asleep, even if the bot isn't running — Alpaca fires the stop automatically. This is the primary downside protection.

### Execution sequence

1. **SELLs first** — close positions with sell signals to free up slots
2. **Refresh positions** — re-query Alpaca to get accurate open position count
3. **BUYs** — open new positions up to the slot limit

### Position sizing

```
qty = max(1, floor($10,000 / current_price))
stop_price = round(entry_price × 0.95, 2)
```

With 10 maximum positions and $10,000 per position, the fully deployed portfolio is $100,000. Each position is exactly 10% of capital with a 5% maximum loss = 0.5% of total capital at risk per trade.

### Trade logging

Every successful BUY is immediately appended to `datasets/trade_log.csv` with:

- Trade ID (date + ticker)
- Ticker, strategy, robustness score
- Entry date, entry price, quantity
- Status: OPEN

---

## 9. P&L Tracker

**File:** `tracker.py`

Runs daily after `bot.py`. Checks all OPEN trades in `trade_log.csv` against live Alpaca data to detect exits and compute P&L.

### Exit detection

For each OPEN trade:

1. Query Alpaca for current open positions
2. If the ticker is still in positions → still open, skip
3. If the ticker is NOT in positions → something closed it
4. Query Alpaca's closed orders for that ticker after the entry date
5. Find the most recent sell-side fill
6. Determine exit reason: `stop_loss` (order type = stop) or `signal` (market sell by bot)
7. Compute P&L and update `trade_log.csv`

### Summary statistics

```
Total P&L
Win rate (% of closed trades profitable)
Profit factor (gross wins ÷ gross losses)
Avg win $ / Avg loss $
Exit breakdown (stop loss vs signal)
Per-strategy P&L breakdown
Recent closed trades table
Current open positions
```

### Evaluation criteria (6-week milestone)

| Metric             | Target | Meaning                                 |
| ------------------ | ------ | --------------------------------------- |
| Win rate           | ≥ 50%  | Strategy finds real edges               |
| Profit factor      | ≥ 1.3  | Winners meaningfully exceed losers      |
| Stop loss hit rate | < 40%  | Entries are well-timed                  |
| Closed trades      | ≥ 10   | Enough sample size to trust the numbers |

---

## 10. Automation

**Scheduler:** macOS launchd (not cron — launchd runs as the logged-in user with full file permissions)

**Schedule:** 9:35am ET, Monday through Friday (5 minutes after market open, allowing initial price action to settle)

**Plist location:** `~/Library/LaunchAgents/com.alphascanner.daily.plist`

**Daily run sequence:**

```
9:35am ET
    │
    ├── [1/4] data.py --topup
    │         Updates all 735 ticker CSVs with latest daily close via yfinance
    │         ~2-3 minutes
    │
    ├── [2/4] signals.py
    │         Checks 29 validated survivors for BUY/SELL/HOLD signals
    │         ~30 seconds
    │
    ├── [3/4] bot.py
    │         Places orders on Alpaca, logs entries
    │         ~10 seconds
    │
    └── [4/4] tracker.py
              Detects new exits, updates P&L, prints summary
              ~10 seconds
```

**Logs:**

- Full pipeline output: `datasets/daily_YYYY-MM-DD.log` (via `run_daily.sh`)
- launchd stdout: `datasets/launchd_out.log`
- launchd stderr: `datasets/launchd_err.log`

**Manual commands:**

```bash
# Run full pipeline manually
./run_daily.sh

# Run signals only (no trades)
./run_daily.sh --signals-only

# Check P&L anytime
python3 tracker.py --summary-only

# Re-run walk-forward validation (after adding strategies or quarterly)
python3 validate.py

# Re-run full backtest (after adding data or strategies)
python3 main.py

# Full data refresh from WRDS
python3 data.py

# yfinance top-up only
python3 data.py --topup
```

---

## 11. Performance Benchmarks

_As of initial backtest (2015–2026, 735 tickers)_

| Stat                                              | Value                           |
| ------------------------------------------------- | ------------------------------- |
| Total strategy-ticker combinations tested         | 5,145                           |
| Qualifying results (≥ 5 trades, Sharpe > 0)       | 5,048                           |
| Unique tickers with at least one qualifying combo | 735                             |
| Average Sharpe ratio across all combos            | 0.372                           |
| Average win rate across all combos                | 62.8%                           |
| Highest robustness score                          | 423.4 (ADI + BBands)            |
| Top combo total return                            | 1,192% (ADI + BBands, 10 years) |

### Top 5 strategy-ticker combinations

| Rank | Ticker | Strategy     | Robustness | Return | Sharpe | Win Rate |
| ---- | ------ | ------------ | ---------- | ------ | ------ | -------- |
| 1    | ADI    | BBands(20,2) | 423.4      | 1192%  | 1.245  | 87.2%    |
| 2    | SYK    | RSI(14)      | 400.6      | 499%   | 1.145  | 89.7%    |
| 3    | CAH    | BBands(20,2) | 387.9      | —      | —      | —        |
| 4    | TJX    | RSI(14)      | 295.2      | —      | —      | —        |
| 5    | LLY    | BBands(20,2) | 243.5      | —      | —      | —        |

---

## 12. Risk Management

The system has three independent layers of risk control:

### Layer 1 — Per-trade stop loss (Alpaca server-side)

Every position carries a hard 5% stop loss placed as an OTO order on Alpaca's servers. Fires automatically regardless of whether the bot is running or the Mac is awake. Maximum loss per trade: $500 (0.5% of $100k capital).

### Layer 2 — Position concentration limit

Maximum 10 open positions at once. No single position exceeds 10% of portfolio. Prevents concentration risk from a single bad trade wiping out the account.

### Layer 3 — Walk-forward validation filter

Only combos with OOS Sharpe ≥ 0.3, decay ≥ 0.4, profitable in the majority of test windows, and appearing in at least 3 of 9 validation windows are traded. RSI(21) is permanently excluded. This replaces the raw IS robustness threshold used in earlier versions.

### Layer 4 — Market regime filter

Every morning, `signals.py` fetches SPY and checks whether it's above its 200-day moving average. If SPY is below the 200-day MA (bearish regime), all new BUY signals are suppressed — the system moves to cash and waits. SELL signals and stop-losses still execute normally. This protects the mean-reversion strategies (RSI, BBands) from buying into sustained downtrends.

### Layer 5 — Strategy diversification

The active strategies span mean reversion (RSI, BBands), momentum (MACD), and dual-confirmation (BBands+RSI). No single market regime kills all strategies simultaneously.

---

## 14. Recession & Bear Market Behaviour

### What the data covers

The backtest and validation windows span 2000–2024, which includes every major US market regime of the past 25 years:

- **2000–2002 dot-com crash** — NASDAQ fell ~78%, S&P 500 fell ~49% over 2.5 years
- **2008–2009 financial crisis** — S&P 500 fell ~56% over 17 months (validation window 2 tests directly against this)
- **2011 Euro sovereign crisis** — sharp mid-year correction
- **2015 oil crash / China slowdown** — S&P 500 corrected ~12%
- **2018 vol spike** — Q4 selloff of ~20%
- **2020 COVID crash** — sharp 34% decline in ~5 weeks, followed by rapid recovery
- **2022 bear market** — slow grind of -18% driven by rate hikes

### Strategy behaviour by type in a downturn

**RSI(14) and BBands(20,2) — most vulnerable without the regime filter**
Both are mean reversion strategies. They buy when something looks "oversold." In a genuine recession, stocks can stay oversold for 6–12 months — RSI hits 30 and keeps falling to 15. The strategy buys the dip, the stop loss fires. Then it buys the next dip. Stop fires again. The regime filter addresses this directly.

**RSI(14)+Trend(200) — most protected by design**
The 200-day MA filter blocks entries on downtrending stocks. In a recession, most stocks fall below their 200-day MA quickly and stay there — this strategy simply stops trading them and waits.

**MACD — moderately protected**
Momentum-based, not mean reversion. Won't generate a BUY signal if momentum is consistently negative. In a sustained downturn it produces very few signals — better than buying into a falling market.

**BBands+RSI — vulnerable without the regime filter**
Requires double confirmation of oversold conditions. In a crash, both conditions can fire simultaneously and persistently as a stock keeps falling.

### The market regime filter (implemented)

Every morning, `signals.py` fetches SPY and compares its current price to the 200-day moving average:

```
Market regime: HEALTHY ▲  |  SPY $722.75  vs  200-day MA $667.95
```

If SPY is below its 200-day MA, all new BUY signals are suppressed:

```
Market regime: BEARISH ▼  |  SPY $362.18  vs  200-day MA $421.04
⚠️  SPY below 200-day MA — new BUY entries suppressed
```

**What this would have done in 2022:** SPY crossed below its 200-day MA in January 2022 and stayed there until November — ~10 months of suppressed BUY entries through the entire bear market. Existing positions and stop-losses still executed normally throughout.

**What this would have done in 2008:** Triggered in January 2008, before most of the drawdown, and held until mid-2009. The system would have been in cash for the worst of the crisis.

### Validation evidence across regimes

With 9 windows now covering 2006–2024:

| Window | Regime | Active Rate | OOS Result |
| ------ | ------ | ----------- | ---------- |
| 2008   | GFC    | 39/50       | Positive   |
| 2011   | Euro crisis | 24/50  | Positive   |
| 2022   | Rate-hike bear | 39/50 | Positive |

The 2011 active rate (24/50) is the lowest — many strategies simply didn't fire in that choppy year. That's the regime filter doing its job passively through strategy mechanics, before the explicit SPY gate was added.

---

## 15. Going Live

When paper trading results meet the evaluation criteria (Section 10), switching to live trading requires three steps:

**1. Open a live Alpaca brokerage account** at alpaca.markets and fund it.

**2. Update `.env` with live API keys:**

```
ALPACA_API_KEY=your_live_api_key
ALPACA_SECRET_KEY=your_live_secret_key
```

**3. Change one line in `bot.py`:**

```python
PAPER = False  # was True
```

Everything else — signals, execution logic, risk management, P&L tracking — works identically on live money.

**Recommendation:** Start with $10,000–20,000 real capital while keeping the remainder in reserve. Validate that live execution matches paper results for 4–6 weeks before scaling to full capital.

---

## 16. Roadmap

### Completed

- ✅ **25-year data history** — CRSP extended from 2015 back to 2000, covering dot-com crash and 2008 GFC
- ✅ **9-window walk-forward validation** — stress-tested across 2006, 2008, 2011, 2015, 2018, 2021, 2022, 2023, 2024
- ✅ **Market regime filter** — SPY 200-day MA gate in `signals.py` and `bot.py`; suppresses BUY entries in bearish markets, exits still execute normally

### Near-term (after 6-week paper evaluation — ~June 9 2026)

- **Live trading migration** — flip `PAPER = False` in `bot.py`, fund live Alpaca account with $10–20k
- **Strategy 8 — Heikin Ashi + Supertrend + ADX** — triple-confirmation trend-following strategy, add to `strategies.py` then re-run `main.py` + `validate.py`
- **Rolling universe refresh** — quarterly CRSP re-pull to capture new tickers and remove long-delisted ones

### Month 2–3

- **Transaction cost modelling** — add 5–10 bps slippage per trade to backtest; will give more realistic IS vs OOS comparison
- **Dynamic position sizing** — scale position size by OOS Sharpe score rather than flat $10,000

### Later

- Email/SMS alerts on trade execution and stop loss hits
- Web dashboard — P&L, open positions, strategy performance over time
- Expand universe to international ADRs and sector ETFs

---

## Dependencies

```
vectorbt       # Backtesting engine and technical indicators
pandas         # Data manipulation
yfinance       # Daily price top-up
alpaca-py      # Brokerage API (paper and live trading)
psycopg2       # PostgreSQL driver for WRDS connection
python-dotenv  # Environment variable management
```

---

## Credentials

Store in `.env` — never commit to version control:

```
ALPACA_API_KEY=...
ALPACA_SECRET_KEY=...
WRDS_USER=ksugsvanvit
WRDS_PASSWORD=...
```

---
