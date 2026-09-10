import pandas as pd

# The live, chosen version of tests/sma/sma.py's crossover logic for AAPL --
# tests/sma/sma.py stays the research tool (grid search, MCPT); this is deliberately smaller:
# given today's bars, what's today's position? No backtest-only columns, no optimization.
#

SYMBOL = "AAPL"
FAST_WINDOW = 5
SLOW_WINDOW = 20
TARGET_ALLOCATION_PCT = 1.0  # fraction of account equity to allocate when the signal is long


def compute_signal(df: pd.DataFrame) -> int:
    # df is assumed sorted oldest -> newest with a 'close' column, e.g. from get_bars()
 
   
    fast_ma = df['close'].rolling(window=FAST_WINDOW).mean()
    slow_ma = df['close'].rolling(window=SLOW_WINDOW).mean()
    return int(fast_ma.iloc[-1] > slow_ma.iloc[-1])
