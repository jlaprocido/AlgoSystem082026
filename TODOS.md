# TODOs

## Make the daily run start on time (P1)

**What:** Trigger `run_daily` from outside GitHub's scheduler (e.g. cron-job.org calling `workflow_dispatch`), or move to an always-on VM with a real local-time cron.

**Why:** 10 of 34 `run_daily` rows in `data/orders/trade_log.csv` are `market_closed` (about 29%). Runs are scheduled for 14:45 UTC but land between 18:20 and 22:14 UTC; anything after 20:00 UTC finds the market closed and does nothing. Extra cron lines don't help because they use the same scheduler.

**Pros:** The strategy acts on every trading day, so live results match the backtest and buy & hold comparison.

**Cons:** An outside scheduler adds a repo-scoped token and a schedule that lives outside the repo; a VM adds server upkeep.

**Context:** Option A (outside scheduler): fine-grained GitHub token limited to this repo with Actions write, one HTTP POST per trading day to the workflow dispatch endpoint. The same-day order ID (`AAPL-sma-YYYY-MM-DD`) already blocks duplicate orders. Option B (VM) matches the VM move already mentioned in the workflow comments. Decided 2026-11-01 in /plan-ceo-review: deferred, not rejected. Update 2026-11-01: option B chosen -- deploy/ scripts and dashboard.yml are written; remaining manual steps (create the VM, deploy key, cutover) are in README "Deployment (always-on VM)".

**Effort:** A: human ~1h / CC ~15min (S). B: human ~1 day / CC ~1h (L).

**Depends on:** nothing.
