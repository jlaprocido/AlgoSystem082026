import pandas as pd
import matplotlib.pyplot as plt
from tqdm import tqdm

from tests.ibit_overnight.ibit_overnight import (
    get_ibit_bars, optimize_overnight, overnight_returns, overnight_signal, profit_factor, get_overnight_permutation,
)


# all of IBIT's history is the in-sample window: it's shorter than the 4 years other strategies use
train_df = get_ibit_bars()
best_lookback, best_real_pf = optimize_overnight(train_df)
plain_real_pf = profit_factor(overnight_returns(train_df, overnight_signal(train_df)))
print("In-sample PF", best_real_pf, "Best Filter Lookback", best_lookback)
print("Plain rule PF (no filter)", plain_real_pf)


n_permutations = 1000
perm_better_count = 1
plain_better_count = 1
permuted_pfs = []
print("In-Sample MCPT")
for perm_i in tqdm(range(1, n_permutations)):
    train_perm = get_overnight_permutation(train_df)
    _, best_perm_pf = optimize_overnight(train_perm)
    plain_perm_pf = profit_factor(overnight_returns(train_perm, overnight_signal(train_perm)))

    if best_perm_pf >= best_real_pf:
        perm_better_count += 1
    if plain_perm_pf >= plain_real_pf:
        plain_better_count += 1

    permuted_pfs.append(best_perm_pf)

# Psuedo-P-Value: the % chance that this strategy is based on data mining bias
# a good P-Value is less than 1% (0.01) and a bad P-Value is greater than 5% (0.05)
insample_mcpt_pval = perm_better_count / n_permutations
print(f"In-sample MCPT P-Value: {insample_mcpt_pval}")
print(f"Plain rule MCPT P-Value: {plain_better_count / n_permutations}")

plt.style.use('dark_background')
pd.Series(permuted_pfs).hist(color='blue', label='Permutations')
plt.axvline(best_real_pf, color='red', label='Real')
plt.xlabel("Profit Factor")
plt.title(f"In-sample MCPT. P-Value: {insample_mcpt_pval}")
plt.grid(False)
plt.legend()
plt.show()
