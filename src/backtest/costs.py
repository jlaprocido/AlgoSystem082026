import pandas as pd


def apply_slippage(signal: pd.Series, returns: pd.Series, slippage_pct: float = 0.0005) -> pd.Series:
    # slippage is charged whenever the position changes, proportional to how much it changed
    # (0 -> 1 or 1 -> 0 is a 1-unit turnover, -1 -> 1 is a 2-unit turnover)
    trade_cost = slippage_pct * signal.diff().abs()
    return signal * returns - trade_cost
