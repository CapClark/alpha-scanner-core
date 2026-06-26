#!/usr/bin/env bash
# Bootstrap an always-on Ubuntu 24.04 host for the strategy_grade.io DAILY executor.
#
# Phase 1 scope: alpha-scanner (as-is) + canslim (--sp500). The heavy weekly research
# (--full --weekly, needs WRDS + the 1.2G ohlcv_full cache) stays on the laptop.
#
# Run as a sudo-capable non-root user. Idempotent: safe to re-run.
set -euo pipefail

BASE="${HOME}/strategy_grade.io"
TZ_WANT="America/New_York"

echo "==> [1/7] Timezone -> ${TZ_WANT}  (cron fires at US market open; DST handled by the OS)"
sudo timedatectl set-timezone "${TZ_WANT}"

echo "==> [2/7] System packages"
sudo apt-get update -y
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
  git python3 python3-venv python3-pip python3-dev build-essential rsync

echo "==> [3/7] Clone repos (from main)"
mkdir -p "${BASE}"; cd "${BASE}"
[ -d alpha-scanner-core ] || git clone https://github.com/CapClark/alpha-scanner-core.git
[ -d canslim-core ]       || git clone https://github.com/CapClark/canslim-core.git

echo "==> [4/7] Python venvs + deps (a few minutes — vectorbt/numba compile)"
for d in alpha-scanner-core canslim-core; do
  cd "${BASE}/${d}"
  [ -d venv ] || python3 -m venv venv
  ./venv/bin/pip install -q --upgrade pip wheel
  ./venv/bin/pip install -q -r requirements.txt
  echo "    ${d}: deps installed ($(./venv/bin/python --version))"
done

echo "==> [5/7] Link canslim .env -> alpha .env (matches laptop layout)"
ln -sf ../alpha-scanner-core/.env "${BASE}/canslim-core/.env"

echo "==> [6/7] Pre-flight (secrets + benchmark cache must be copied separately)"
MISSING=0
if [ ! -f "${BASE}/alpha-scanner-core/.env" ]; then
  echo "  !! MISSING alpha-scanner-core/.env  — scp it from the laptop (see deploy/README.md)"; MISSING=1
fi
if [ -d "${BASE}/alpha-scanner-core/datasets/cache" ]; then
  echo "  benchmark cache: $(ls "${BASE}/alpha-scanner-core/datasets/cache" | wc -l) ticker files"
else
  echo "  !! MISSING alpha-scanner-core/datasets/cache — rsync it from the laptop (see README)"; MISSING=1
fi

echo "==> [7/7] Install crontab (schedule times = ${TZ_WANT})"
sed "s|__BASE__|${BASE}|g" "${BASE}/alpha-scanner-core/deploy/crontab.txt" | crontab -
crontab -l

echo ""
if [ "${MISSING}" = 1 ]; then
  echo "SETUP PARTIAL — copy the missing secrets/cache, then verify with a dry run:"
else
  echo "SETUP OK — verify with a dry run before the first live cron fire:"
fi
echo "  cd ${BASE}/alpha-scanner-core && ./run_daily.sh --signals-only"
echo "  cd ${BASE}/canslim-core       && ./run_daily.sh --sp500 --signals-only"
