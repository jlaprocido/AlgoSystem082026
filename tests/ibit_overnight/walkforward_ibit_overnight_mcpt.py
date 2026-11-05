import pandas as pd
import matplotlib.pyplot as plt
from tqdm import tqdm

from tests.ibit_overnight.ibit_overnight import (
    get_ibit_bars, walkforward_overnight, overnight_returns, profit_factor, get_overnight_permutation, TRAIN_LOOKBACK,
)


def walkforward_pf(ohlc: pd.DataFrame) -> float:
    signal = pd.Series(walkforward_overnight(ohlc), index=ohlc.index)
    rets = overnight_returns(ohlc, signal.fillna(0.0))
    return profit_factor(rets[signal.notna()].dropna())


df = get_ibit_bars()
real_wf_pf = walkforward_pf(df)
print("Walk-forward PF", real_wf_pf)

n_permutations = 1000
perm_better_count = 1
permuted_pfs = []
print("Walkforward MCPT")
for perm_i in tqdm(range(1, n_permutations)):
    wf_perm = get_overnight_permutation(df, start_index=TRAIN_LOOKBACK)
    perm_pf = walkforward_pf(wf_perm)

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
