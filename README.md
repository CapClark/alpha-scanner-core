# Alpha Scanner

A systematic swing-trading bot. It backtests 7 technical strategies against 735 US stocks over 25 years, keeps only the strategy-ticker pairs that survive out-of-sample validation, and trades that shortlist automatically through Alpaca with server-side stop losses.

## Why I built it

My dad has traded full-time for about a decade and used to send me his setups constantly. Somewhere around the hundredth indicator he explained, I stopped wanting to eyeball charts and started wanting to know whether any of it actually held up over 25 years of data. So I built the thing that would tell me. It runs on paper money on a schedule, logs every trade, and grades itself.

## The core idea

Not every strategy works on every stock. RSI mean-reversion can do well on a range-bound pharma name and terribly on a high-momentum tech name. So instead of picking one strategy and spraying it across the market, this tests every strategy on every stock, scores each pairing by how *robustly* it held up (not just raw return), and only trades the pairings that had a real, repeatable edge.

The catch every quant hits: test 5,000 combinations and some will look brilliant on pure luck. The fix here is walk-forward validation — train on history, test on years the strategy never saw, and throw out anything whose edge evaporates.

## How it runs

Six files, one morning pipeline:

```
data.py       Pull 25yr history from WRDS/CRSP, top up daily via yfinance   (735 price CSVs)
main.py       Backtest 7 strategies x 735 tickers, rank by robustness       (~5,000 combos)
validate.py   Walk-forward test the top combos across 9 market regimes       (29 survivors)
signals.py    Each morning, check the 29 survivors for a live BUY/SELL/HOLD
bot.py        Place OTO bracket orders on Alpaca with a 5% stop loss
tracker.py    Detect exits, compute win rate / profit factor / P&L
```

`run_daily.sh` chains steps at 9:35am ET (5 min after open) via launchd. `main.py` and `validate.py` are periodic refreshes, not daily.

## The strategies

Seven classic setups, each reduced to boolean entry/exit series and simulated with `vectorbt`:

| Strategy | Type | In live watchlist |
| --- | --- | --- |
| BBands + RSI (dual confirm) | Mean reversion | Yes — best out-of-sample |
| RSI(14) | Mean reversion | Yes |
| Bollinger Bands (20, 2σ) | Mean reversion | Yes |
| MACD crossover | Momentum | Yes |
| RSI(21) | Mean reversion | No — negative OOS Sharpe |
| RSI(14) + 200-day trend filter | Mean reversion + trend | Backtest only |
| MA cross (50/200) | Trend | Backtest only |

## The robustness score

Every strategy-ticker pairing gets one number:

```python
robustness_score = trade_count * sharpe * win_rate * profit_factor
```

(profit_factor capped at 10, win_rate as a decimal, anything with <5 trades or Sharpe ≤ 0 scored zero.)

The point is that a 500% return off 3 lucky trades should lose to a 150% return proven across 35 trades. Multiplying by trade_count and win_rate makes it so. A strategy has to be right often, not just once and big.

## Walk-forward validation

Ranking on the full backtest overfits, so the top combos get retested on 9 rolling windows, each ending in a different market regime (dot-com aftermath 2006, GFC 2008, Euro crisis 2011, oil crash 2015, vol spike 2018, COVID recovery 2021, rate-hike bear 2022, plus 2023–24). A combo must appear in at least 3 windows to qualify.

Survivor filters:

```python
oos_sharpe     >= 0.3    # still risk-adjusted positive out-of-sample
sharpe_decay   >= 0.4    # keeps at least 40% of its in-sample Sharpe
pct_profitable >= 0.5    # profitable in most test windows
windows_tested >= 3      # robust across regimes, not one lucky year
```

29 combos survived. The finding that changed the system: in-sample ranking did **not** reliably predict out-of-sample ranking (rank correlation insignificant, p > 0.05, in every window). So the live watchlist is sorted by out-of-sample Sharpe from validation, not by the raw backtest score. RSI(21) was the one strategy with a negative OOS Sharpe across the board, so it's permanently excluded from live trading even though it looks fine in-sample.

## Risk controls

- **Server-side stop loss.** Every buy is an OTO bracket order with a 5% stop that lives on Alpaca's servers, so it fires even if my machine is asleep. Max ~0.5% of capital at risk per trade.
- **Concentration limit.** Never more than 10 open positions, $10k each, so no single name is over 10% of the book.
- **Market regime filter.** Each morning it checks SPY against its 200-day MA. If SPY is below it (bearish), new buys are suppressed and the system sits in cash — exits and stops still fire. In 2022 that would have meant ~10 months of no new entries through the bear market.
- **Validation gate.** Only the 29 walk-forward survivors are tradable at all.

## Results

From the backtest and paper trading (this is a backtest plus paper account, not audited live returns):

| Ticker | Strategy | Robustness | Return (25yr) | Sharpe | Win rate |
| --- | --- | --- | --- | --- | --- |
| ADI | BBands(20,2) | 423.4 | 1192% | 1.25 | 87% |
| SYK | RSI(14) | 400.6 | 499% | 1.15 | 90% |
| CAH | BBands(20,2) | 387.9 | — | — | — |
| TJX | RSI(14) | 295.2 | — | — | — |
| LLY | BBands(20,2) | 243.5 | — | — | — |

Across all ~5,000 qualifying combos: average win rate 63%, average Sharpe 0.37. The spread matters more than the top line — most combos are mediocre, which is the point of filtering hard.

## Running it

```bash
pip install -r requirements.txt
cp .env.example .env        # fill in your own Alpaca + WRDS credentials

python3 data.py             # full history pull from WRDS (one-time)
python3 main.py             # backtest + rank
python3 validate.py         # walk-forward validation (~10 min)
./run_daily.sh              # full daily pipeline (or --signals-only for no trades)
python3 tracker.py --summary-only   # check P&L anytime
```

Defaults to Alpaca paper trading. Going live is a funded live account, live keys in `.env`, and flipping `PAPER = False` in `bot.py` — everything else is identical.

## Stack

`vectorbt` (backtesting + indicators), `pandas` / `numpy`, `yfinance` (daily top-up), `alpaca-py` (brokerage), `psycopg2` (WRDS/CRSP over Postgres), `python-dotenv`. Historical data is CRSP via WRDS — the same split/dividend-adjusted, survivorship-aware dataset academic researchers use — with yfinance filling the gap from where CRSP ends to today.

## Disclaimer

Built to learn quant systems end to end, not to give financial advice. Backtested and paper-traded results do not predict live returns. Trade your own money at your own risk.
