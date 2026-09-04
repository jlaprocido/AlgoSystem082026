import pandas as pd
import numpy as np
import datetime as dt
import matplotlib.pyplot as plt
from tqdm import tqdm

from tests.three_sma.three_sma import optimize_three_sma_strategy, INTERVAL
from tests.bar_permute import get_permutation
from src.data.market_data import get_bars


df = get_bars("SPY", dt.date(2016, 1, 1), dt.date.today()+dt.timedelta(days=1), source="yfinance", interval=INTERVAL)

train_df = df[(df['timestamp'].dt.year >= 2016) & (df['timestamp'].dt.year < 2020)]
best_windows, best_real_pf = optimize_three_sma_strategy(train_df, interval=INTERVAL)
print("In-sample PF", best_real_pf, "Best Windows (fast, med, slow)", best_windows)


n_permutations = 200
perm_better_count = 1
permuted_pfs = []
print("In-Sample MCPT")
for perm_i in tqdm(range(1, n_permutations)):
    train_perm = get_permutation(train_df)
    _, best_perm_pf = optimize_three_sma_strategy(train_perm, interval=INTERVAL)  # type: ignore[reportArgumentType]

    if best_perm_pf >= best_real_pf:
        perm_better_count += 1

    permuted_pfs.append(best_perm_pf)

# Psuedo-P-Value: the % chance that this strategy is based on data mining bias
# a good P-Value is less than 1% (0.01) and a bad P-Value is greater than 5% (0.05)
insample_mcpt_pval = perm_better_count / n_permutations
print(f"In-sample MCPT P-Value: {insample_mcpt_pval}")

plt.style.use('dark_background')
pd.Series(permuted_pfs).hist(color='blue', label='Permutations')
plt.axvline(best_real_pf, color='red', label='Real')
plt.xlabel("Profit Factor")
plt.title(f"In-sample MCPT. P-Value: {insample_mcpt_pval}")
plt.grid(False)
plt.legend()
plt.show()
