# Polymarket FAA Attribution 02 - Competition Entry

This repository contains our entry for `make.fun`'s **polymarket-faa-attribution-02** competition. The task is to forecast prediction-market Yes prices as quantiles ($0.05, 0.25, 0.5, 0.75, 0.95$) over a 240-minute horizon.

## Forecasting Methodology

Our entry implements an advanced **dual-leg empirical-quantile ensemble**, averaged element-by-element in price space:

1. **Dual-Leg Structure**:
   - **Model A (Raw Price Space)**: Operates directly on raw price changes with $\sigma_{\text{floor}} = 0.0008$, width factor $= 0.55$, and pooling denominator $= 400$.
   - **Model B (Log-Odds Space)**: Clips prices into $[0.0005, 0.9995]$, applies the logit transformation $z = \ln(p / (1-p))$, runs the pipeline, and maps quantiles back via the logistic function ($\sigma_{\text{floor}} = 0.02$, width factor $= 0.65$, pooling denominator $= 800$).

2. **One-Step Changes & Baseline Scale ($\sigma_1$)**:
   - Computes one-step changes $\Delta x_t = x[t] - x[t-1]$ and establishes a robust baseline per-minute scale $\sigma_1$, floored at $\sigma_{\text{floor}}$.

3. **Volatility Trend**:
   - Computes an EWMA of absolute one-step changes using a 45-minute half-life ($\alpha = 1 - 2^{-1/45}$), normalized by the full-series mean absolute change to yield a volatility ratio. Recent higher volatility widens spreads, while calmer periods narrow them.

4. **Horizon Grid & Recent-Window Blending**:
   - Evaluates changes across 19 horizon grid points $H = [1, 2, 3, 4, 5, 7, 9, 12, 16, 21, 28, 37, 49, 65, 86, 114, 151, 200, 240]$.
   - For long series ($n - 360 > h$) with at least 60 changes in the recent 360-minute window, recent changes are combined (duplicate-weighted once) with full-history changes.

5. **Cross-Market Pooling**:
   - Scales each market's changes by the ratio of a common reference scale (median horizon scale $\sigma_h$) to its own horizon scale $\sigma_h$.
   - Pools scaled changes across all markets in the case and blends the market's own empirical quantiles with the pooled quantiles using sample-size-dependent weighting (`pool_denom / (pool_denom + n_changes)`).

6. **Quantile Construction & Interpolation**:
   - Centers around persistence $x[n-1]$ adjusted by the median change, scaling deviations from the median change by `width_factor`.
   - Linearly interpolates quantiles across the horizon grid to generate exact minute-by-minute forecasts for minutes $1 \dots 240$.

7. **Post-Processing**:
   - Averages Model A and Model B price-space quantiles element-by-element.
   - Clips forecasts into $[0, 1]$.
   - Enforces non-decreasing order across the 5 quantile columns for each row.
   - Rounds values to 6 decimal places.

## Local Validation

- **Execution**: Run via Python 3.13 standard library with zero external dependencies.
- **Verification**: Tested on practice cases (`p00.in` through `p05.in`).
- **Determinism**: Verified through dual independent runs with byte-for-byte `diff` verification.
- **Output Integrity**: Confirmed correct JSON schema, exact market coverage, 240 rows of 5 non-decreasing quantile values in $[0, 1]$, and sub-second execution speed per case.
