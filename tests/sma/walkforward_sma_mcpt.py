import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from tqdm import tqdm
import datetime as dt

from tests.bar_permute import get_permutation
from tests.sma.sma import walkforward_sma, INTERVAL
from src.data.market_data import get_bars
from src.backtest.costs import apply_slippage
from src.bar_config import BAR_CONFIG

df = get_bars("AAPL", dt.date(2016, 1, 1), dt.date.today()+dt.timedelta(days=1), interval=INTERVAL)

# use this symbol's own first ~8 years of data as the walk-forward window, rather than a fixed
# calendar range -- a hardcoded "2016-2020" assumes every symbol was already trading by 2016,
# which breaks (empty slice, crashes in get_permutation) for any more recent IPO. 8 years (not 4)
# because train_window below already consumes ~4 years just for the initial training lookback --
# the slice needs to be meaningfully longer than train_window or there's no bars left to actually
# walk forward across (this is what "252*2" vs. a 4-year slice buys walkforward_donchian_mcpt.py)
train_years = 8
first_year = int(df['timestamp'].dt.year.min())
df = df[df['timestamp'].dt.year < first_year + train_years]

df['r'] = np.log(df['close']).diff().shift(-1) # type: ignore[reportAttributeAccessIssue]

train_window = BAR_CONFIG[INTERVAL]["train_lookback"]
df['sma_wf_signal'] = walkforward_sma(df, interval=INTERVAL, train_lookback=train_window)

sma_rets = apply_slippage(df['sma_wf_signal'], df['r'])
real_gross_loss = sma_rets[sma_rets < 0].abs().sum()
real_wf_pf = sma_rets[sma_rets > 0].sum() / real_gross_loss if real_gross_loss > 0 else np.nan

n_permutations = 200
perm_better_count = 1
permuted_pfs = []
print("Walkforward MCPT")
for perm_i in tqdm(range(1, n_permutations)):
    wf_perm = get_permutation(df, start_index=train_window)

    wf_perm['r'] = np.log(wf_perm['close']).diff().shift(-1) # type: ignore[reportAttributeAccessIssue]
    wf_perm_sig = walkforward_sma(wf_perm, interval=INTERVAL, train_lookback=train_window) # type: ignore[reportArgumentType]
    perm_rets = apply_slippage(pd.Series(wf_perm_sig, index=wf_perm.index), wf_perm['r'])  # type: ignore[reportArgumentType]
    perm_gross_loss = perm_rets[perm_rets < 0].abs().sum()
    perm_pf = perm_rets[perm_rets > 0].sum() / perm_gross_loss if perm_gross_loss > 0 else np.nan

    if perm_pf >= real_wf_pf:
        perm_better_count += 1

    permuted_pfs.append(perm_pf)


walkforward_mcpt_pval = perm_better_count / n_permutations

# Psuedo-P-Value: the % chance that this strategy is based on data mining bias
# a good P-Value is less than 1% (0.01) and a bad P-Value is greater than 5% (0.05) (5% is fine for less than 1 year)
print(f"Walkforward MCPT P-Value: {walkforward_mcpt_pval}")


plt.style.use('dark_background')
pd.Series(permuted_pfs).hist(color='blue', label='Permutations')
plt.axvline(real_wf_pf, color='red', label='Real')
plt.xlabel("Profit Factor")
plt.title(f"Walkforward MCPT. P-Value: {walkforward_mcpt_pval}")
plt.grid(False)
plt.legend()
plt.show()
