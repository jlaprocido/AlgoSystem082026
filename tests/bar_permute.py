# Good for cypto data, DAILY STOCK DATA, but not intraday due to the jump between open and close
# Read "Permutation and randomization tests for trading system development to fix this
#
# Volume is permuted alongside the intrabar (high/low/close) shuffle, using the same
# permutation index -- so a bar's volume stays paired with that bar's own range/shape,
# just relocated to a different time slot. This preserves the price-volume relationship
# within a bar (e.g. big-range bars tend to have high volume) while still destroying the
# temporal ordering, which is what the permutation test needs.

import numpy as np
import pandas as pd
import datetime as dt
from typing import List, Union
from src.data.market_data import get_bars

def get_permutation(
    ohlc: Union[pd.DataFrame, List[pd.DataFrame]], start_index: int = 0, seed=None
):
    assert start_index >= 0

    np.random.seed(seed)

    if isinstance(ohlc, list):
        time_index = ohlc[0].index
        for mkt in ohlc:
            assert np.all(time_index == mkt.index), "Indexes do not match"
        n_markets = len(ohlc)
    else:
        n_markets = 1
        time_index = ohlc.index
        ohlc = [ohlc]

    n_bars = len(ohlc[0])

    perm_index = start_index + 1
    perm_n = n_bars - perm_index

    if perm_n <= 0:
        raise ValueError(
            f"Not enough bars to permute: got {n_bars} bars with start_index={start_index}, need at "
            f"least {start_index + 2}. A common cause is an empty date-range slice -- e.g. a symbol "
            f"that didn't start trading until after the training window begins."
        )

    start_bar = np.empty((n_markets, 4))
    start_volume = np.empty(n_markets)
    relative_open = np.empty((n_markets, perm_n))
    relative_high = np.empty((n_markets, perm_n))
    relative_low = np.empty((n_markets, perm_n))
    relative_close = np.empty((n_markets, perm_n))
    log_volume = np.empty((n_markets, perm_n))

    for mkt_i, reg_bars in enumerate(ohlc):
        log_bars = np.log(reg_bars[['open', 'high', 'low', 'close']])

        # Get start bar
        start_bar[mkt_i] = log_bars.iloc[start_index].to_numpy()  # type: ignore
        start_volume[mkt_i] = np.log(reg_bars['volume'].iloc[start_index])

        # Open relative to last close
        r_o = (log_bars['open'] - log_bars['close'].shift()).to_numpy()  # type: ignore

        # Get prices relative to this bars open
        r_h = (log_bars['high'] - log_bars['open']).to_numpy()  # type: ignore
        r_l = (log_bars['low'] - log_bars['open']).to_numpy()  # type: ignore
        r_c = (log_bars['close'] - log_bars['open']).to_numpy()  # type: ignore
        bar_volume = np.log(reg_bars['volume']).to_numpy()  # type: ignore

        relative_open[mkt_i] = r_o[perm_index:]
        relative_high[mkt_i] = r_h[perm_index:]
        relative_low[mkt_i] = r_l[perm_index:]
        relative_close[mkt_i] = r_c[perm_index:]
        log_volume[mkt_i] = bar_volume[perm_index:]

    idx = np.arange(perm_n)

    # Shuffle intrabar relative values (high/low/close) and volume together, so a bar's
    # range and volume stay paired -- they just move to a different time slot
    perm1 = np.random.permutation(idx)
    relative_high = relative_high[:, perm1]
    relative_low = relative_low[:, perm1]
    relative_close = relative_close[:, perm1]
    log_volume = log_volume[:, perm1]

    # Shuffle last close to open (gaps) seprately
    perm2 = np.random.permutation(idx)
    relative_open = relative_open[:, perm2]

    # Create permutation from relative prices
    perm_ohlc = []
    for mkt_i, reg_bars in enumerate(ohlc):
        perm_bars = np.zeros((n_bars, 4))
        perm_vol = np.zeros(n_bars)

        # Copy over real data before start index
        log_bars = np.log(reg_bars[['open', 'high', 'low', 'close']]).to_numpy().copy()  # type: ignore
        perm_bars[:start_index] = log_bars[:start_index]
        perm_vol[:start_index] = np.log(reg_bars['volume']).to_numpy()[:start_index]  # type: ignore

        # Copy start bar
        perm_bars[start_index] = start_bar[mkt_i]
        perm_vol[start_index] = start_volume[mkt_i]

        for i in range(perm_index, n_bars):
            k = i - perm_index
            perm_bars[i, 0] = perm_bars[i - 1, 3] + relative_open[mkt_i][k]
            perm_bars[i, 1] = perm_bars[i, 0] + relative_high[mkt_i][k]
            perm_bars[i, 2] = perm_bars[i, 0] + relative_low[mkt_i][k]
            perm_bars[i, 3] = perm_bars[i, 0] + relative_close[mkt_i][k]
            perm_vol[i] = log_volume[mkt_i][k]

        perm_bars = np.exp(perm_bars)
        perm_vol = np.exp(perm_vol)
        perm_bars = pd.DataFrame(perm_bars, index=time_index, columns=['open', 'high', 'low', 'close'])
        perm_bars['volume'] = perm_vol

        perm_ohlc.append(perm_bars)

    if n_markets > 1:
        return perm_ohlc
    else:
        return perm_ohlc[0]

if __name__ == '__main__':
    
    import matplotlib.pyplot as plt
    
    aapl_real = get_bars("AAPL", dt.date(2020, 1, 1), dt.date.today()+dt.timedelta(days=1), interval="1d")
    aapl_real = aapl_real[(aapl_real['timestamp'].dt.year >= 2020) & (aapl_real['timestamp'].dt.year < 2023)]

    aapl_perm = get_permutation(aapl_real)

    aapl_real_r = np.log(aapl_real['close']).diff()  # type: ignore
    aapl_perm_r = np.log(aapl_perm['close']).diff()  # type: ignore

    print(f"Mean. REAL: {aapl_real_r.mean():14.6f} PERM: {aapl_perm_r.mean():14.6f}")
    print(f"Stdd. REAL: {aapl_real_r.std():14.6f} PERM: {aapl_perm_r.std():14.6f}")
    print(f"Skew. REAL: {aapl_real_r.skew():14.6f} PERM: {aapl_perm_r.skew():14.6f}")
    print(f"Kurt. REAL: {aapl_real_r.kurt():14.6f} PERM: {aapl_perm_r.kurt():14.6f}")

    goog_real = get_bars("GOOG", dt.date(2020, 1, 1), dt.date.today()+dt.timedelta(days=1), interval="1d")
    goog_real = goog_real[(goog_real['timestamp'].dt.year >= 2020) & (goog_real['timestamp'].dt.year < 2023)]
    goog_real_r = np.log(goog_real['close']).diff()  # type: ignore

    print("") 

    common_ts = set(aapl_real['timestamp']) & set(goog_real['timestamp'])
    aapl_real = aapl_real[aapl_real['timestamp'].isin(common_ts)].sort_values('timestamp').reset_index(drop=True)
    goog_real = goog_real[goog_real['timestamp'].isin(common_ts)].sort_values('timestamp').reset_index(drop=True)

    permed = get_permutation([aapl_real, goog_real])
    aapl_perm = permed[0]
    goog_perm = permed[1]
    
    aapl_perm_r = np.log(aapl_perm['close']).diff()  # type: ignore
    goog_perm_r = np.log(goog_perm['close']).diff()  # type: ignore
    print(f"AAPL&GOOG Correlation REAL: {aapl_real_r.corr(goog_real_r):5.3f} PERM: {aapl_perm_r.corr(goog_perm_r):5.3f}")

    plt.style.use("dark_background")    
    np.log(aapl_real['close']).diff().cumsum().plot(color='orange', label='AAPL')  # type: ignore
    np.log(goog_real['close']).diff().cumsum().plot(color='purple', label='GOOG')  # type: ignore

    plt.ylabel("Cumulative Log Return")
    plt.title("Real AAPL and GOOG")
    plt.legend()
    plt.show()

    np.log(aapl_perm['close']).diff().cumsum().plot(color='orange', label='AAPL')  # type: ignore
    np.log(goog_perm['close']).diff().cumsum().plot(color='purple', label='GOOG')  # type: ignore
    plt.title("Permuted AAPL and GOOG")
    plt.ylabel("Cumulative Log Return")
    plt.legend()
    plt.show()


