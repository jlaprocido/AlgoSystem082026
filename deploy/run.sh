#!/usr/bin/env bash
# Runs one trading entrypoint on the VM, then commits and pushes whatever state it wrote.
# usage: deploy/run.sh run_daily | intraday_check | eod_summary
set -uo pipefail

module="${1:?usage: deploy/run.sh run_daily|intraday_check|eod_summary}"
repo="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo"

# one job at a time -- the hourly intraday_check can overlap the 9:45 run_daily, and both
# write the same state files and push to the same branch
exec 9>"$repo/.run.lock"
flock -w 600 9 || { echo "could not get the run lock"; exit 1; }

# .env feeds the ntfy alert below; python reads it itself via python-dotenv
set -a; source .env; set +a
source .venv/bin/activate

# pick up any code you pushed from your own machine (so pushing to main deploys to the VM)
git pull --rebase -q || echo "git pull failed -- running the code already on disk"

echo "=== $(date -Is) $module ==="
python -m "src.trading.$module"
status=$?

# a crash is the one failure the bot can't text you about itself
if [ "$status" -ne 0 ]; then
  curl -fsS -m 10 -d "AlgoSystem VM: $module failed (exit $status) -- see logs/cron.log" \
    "https://ntfy.sh/${NTFY_TOPIC}" || true
fi

# same persistence the GitHub workflows did, but with a plain commit message (no [skip ci]) --
# this push is what triggers .github/workflows/dashboard.yml to rebuild the page
git config merge.union.driver "git merge-file --union %A %O %B"
git add data/orders/trade_log.csv data/risk/
if ! git diff --cached --quiet; then
  git commit -q -m "Update trade log / risk state ($module, VM)"
  for i in 1 2 3 4 5; do
    git push -q && break
    echo "Push rejected (attempt $i/5) -- fetching and rebasing..."
    git fetch -q origin main
    git rebase -q origin/main || { git rebase --abort; echo "Real conflict -- leaving the commit for the next run."; break; }
    sleep $((RANDOM % 10 + 1))
  done
fi

exit "$status"
