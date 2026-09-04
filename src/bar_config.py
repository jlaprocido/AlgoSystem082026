# Frequency-dependent constants, keyed by the same interval strings get_bars() accepts.
# Only things that are mechanically derived from bar frequency belong here (annualization,
# walk-forward retrain cadence) - not strategy-specific choices like window size or z-score range,
# since "20 bars" means something different as 20 minutes vs 20 days and has to be tuned by hand.
BAR_CONFIG = {
    "1d": {
        "bars_per_year": 252,
        "train_lookback": 252 * 4,   # ~4 years
        "train_step": 21,            # ~1 month
    },
    "1h": {
        "bars_per_year": 252 * 7,
        "train_lookback": 7 * 252 * 4,
        "train_step": 7 * 21,
    },
    "1m": {
        "bars_per_year": 252 * 390,
        "train_lookback": 390 * 21,  # ~1 month
        "train_step": 390,           # ~1 day
    },
    "30m": {"bars_per_year": 252 * 13, "train_lookback": 13 * 21, "train_step": 13},
    "15m": {"bars_per_year": 252 * 26, "train_lookback": 26 * 21, "train_step": 26},
    "5m":  {"bars_per_year": 252 * 78, "train_lookback": 78 * 21, "train_step": 78},

}
