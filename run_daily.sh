#!/bin/bash
# Daily runner — prices → signals → execute trades
#
# To automate (runs at 9:35am ET Mon–Fri, just after market open):
#   crontab -e
#   35 9 * * 1-5 /Users/kenpeeranat/Documents/strategy_grade.io/alpha-scanner-core/run_daily.sh
#
# For signals only (no trading), run:  ./run_daily.sh --signals-only

cd "$(dirname "$0")"

# Portable venv python — works on the laptop and the cloud host alike.
# The cd above already moved us into the script dir, so pwd is its absolute path.
PYTHON="$(pwd)/venv/bin/python"

SIGNALS_ONLY=false
if [[ "$1" == "--signals-only" ]]; then
    SIGNALS_ONLY=true
fi

LOG="datasets/daily_$(date +%Y-%m-%d).log"

echo "======================================" | tee "$LOG"
echo "DAILY RUN  $(date '+%Y-%m-%d %H:%M')" | tee -a "$LOG"
echo "======================================" | tee -a "$LOG"

# Step 1: top up prices via yfinance
echo "" | tee -a "$LOG"
echo "[ 1/4 ] Updating prices..." | tee -a "$LOG"
$PYTHON data.py --topup 2>&1 | tee -a "$LOG"

# Step 2: generate signals
echo "" | tee -a "$LOG"
echo "[ 2/4 ] Generating signals..." | tee -a "$LOG"
$PYTHON signals.py 2>&1 | tee -a "$LOG"

# Step 3: execute trades (skip if --signals-only)
echo "" | tee -a "$LOG"
if [ "$SIGNALS_ONLY" = true ]; then
    echo "[ 3/4 ] Trading skipped (--signals-only)" | tee -a "$LOG"
else
    echo "[ 3/4 ] Executing trades..." | tee -a "$LOG"
    $PYTHON bot.py 2>&1 | tee -a "$LOG"
fi

# Step 4: update trade log + print P&L summary
echo "" | tee -a "$LOG"
echo "[ 4/4 ] Tracking P&L..." | tee -a "$LOG"
$PYTHON tracker.py 2>&1 | tee -a "$LOG"

echo "" | tee -a "$LOG"
echo "Log saved to $LOG"
