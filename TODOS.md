# TODOs

## Backtest lab

### Reconcile live and backtest fill timing before promoting any strategy

**What:** Compare the backtest's fill (decide at bar close t, earn close t to close t+1, `src/backtest/portfolio.py`) with the live bot's fill (`src/trading/run_daily.py` decides about 10:45 ET the next morning) and decide how the lab models the difference.
**Why:** "Same function drives backtest and live" is true for weights, not fills. A strategy can lose its edge between lab and live.
**Pros:** Keeps lab numbers honest before real money follows them. Feeds the promotion gate in Approach B.
**Cons:** Needs a decision on whether to model an open-fill in the lab or change the live schedule; neither is free.
**Context:** Found in the 2026-11-04 eng review of `docs/designs/strategy-asset-lab-crypto.md` (decision D9). The lab gets `execution_delay_bars` in Approach A, which approximates but does not equal the live morning fill. Start by diffing a week of paper fills against the lab's weights.
**Effort:** M (human: ~1 day / CC: ~30 min)
**Priority:** P2
**Depends on / blocked by:** Approach A results; Approach B's promotion gate design.

### Add a built-in Monte Carlo permutation test (--mcpt N) to the lab

**What:** Let the lab CLI run N permutations of the same bars through the same `strategy_fn` and print a p-value, reusing `tests/bar_permute.py:get_permutation` (keep volume paired with each permuted bar).
**Why:** It is the walk-forward MCPT input to Approach B's promotion gate; today MCPT exists only as per-strategy scripts under `tests/*/`.
**Pros:** One command gives a luck check for any strategy and asset. Reuses trusted permutation code.
**Cons:** Slow on 5m data (N full backtests); medium risk if shuffling and the weights contract disagree.
**Context:** Deferred in the 2026-11-04 CEO review of `docs/designs/strategy-asset-lab-crypto.md` (decision D4) so the first crypto go or no-go answer is not delayed. Start with daily bars; add 1h and 5m once timing is known.
**Effort:** M
**Priority:** P2
**Depends on / blocked by:** Approach A (lab CLI and `strategy_fn` contract); Approach B's promotion gate design.

## Infrastructure

### Run tests/unit in GitHub Actions

**What:** Add `.github/workflows/unit_tests.yml` that runs `python -m pytest tests/unit` on push and pull request, with no secrets (unit tests use synthetic data).
**Why:** The golden-master and parity tests from the lab plan only protect you if they actually run; today `tests/unit` is manual (`requirements-dev.txt`) and none of the three workflows runs pytest.
**Pros:** Accidental changes to numbers fail the push. Teaches the CI habit that production-level code needs.
**Cons:** One more workflow file to maintain; tests that need network must stay out of this job.
**Context:** Deferred in the 2026-11-04 CEO review of `docs/designs/strategy-asset-lab-crypto.md` (decision D8) to keep Approach A's file list and workflows unchanged. Do it right after Approach A lands.
**Effort:** S
**Priority:** P2
**Depends on / blocked by:** Approach A (the unit tests it would run).

## Research

### Start the paper-trading evidence clock early

**What:** As soon as T6 passes, start a daily paper-trading record of the top lab strategy: a manual log, or a run on a separate Alpaca paper account, in parallel with the lab build.
**Why:** Paper trading is the only out-of-sample evidence and its clock (calendar days) cannot be sped up; waiting for Approach B to finish delays the first real evidence by months.
**Pros:** Real fills and real timing data early. Feeds the live-vs-backtest fill-timing TODO.
**Cons:** A separate account run touches order code (Approach B territory); a manual log is slower but risk-free.
**Context:** Deferred in the 2026-11-04 CEO review of `docs/designs/strategy-asset-lab-crypto.md` (decision D11) to keep Approach A lab-only. Start with the manual log.
**Effort:** S
**Priority:** P2
**Depends on / blocked by:** T6 passing; Approach B for an automated paper run.

