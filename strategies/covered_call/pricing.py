"""Black-Scholes options pricing and implied volatility estimation."""

import numpy as np
from scipy.stats import norm


def black_scholes_call(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Price a European call option using Black-Scholes.

    Args:
        S: Current stock price
        K: Strike price
        T: Time to expiration in years
        r: Risk-free rate (annualized)
        sigma: Volatility (annualized)

    Returns:
        Call option price
    """
    if T <= 0:
        return max(S - K, 0.0)
    if sigma <= 0:
        return max(S * np.exp(-r * T) - K * np.exp(-r * T), 0.0)

    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)

    return S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)


def call_delta(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Calculate delta of a European call option."""
    if T <= 0:
        return 1.0 if S > K else 0.0
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    return norm.cdf(d1)


def call_theta(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Calculate theta (daily) of a European call option."""
    if T <= 0:
        return 0.0
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)

    theta = (
        -S * norm.pdf(d1) * sigma / (2 * np.sqrt(T))
        - r * K * np.exp(-r * T) * norm.cdf(d2)
    )
    return theta / 365.0  # per calendar day


def implied_volatility_from_history(
    prices: np.ndarray, window: int = 30, iv_premium: float = 1.3
) -> np.ndarray:
    """Estimate implied volatility from historical prices.

    Uses historical volatility scaled by an IV premium factor, since
    IV typically exceeds realized vol (variance risk premium).

    Args:
        prices: Array of daily closing prices
        window: Lookback window for historical vol calculation
        iv_premium: Multiplier to scale HV to estimated IV (default 1.3x)

    Returns:
        Array of estimated IV values (same length as prices, NaN-filled for warmup)
    """
    log_returns = np.log(prices[1:] / prices[:-1])
    iv_series = np.full(len(prices), np.nan)

    for i in range(window, len(log_returns)):
        hv = np.std(log_returns[i - window : i]) * np.sqrt(252)
        iv_series[i + 1] = hv * iv_premium

    # Backfill the warmup period with the first valid value
    first_valid = window + 1
    if first_valid < len(iv_series):
        iv_series[:first_valid] = iv_series[first_valid]

    # Floor IV at 30% for small-cap names (options market wouldn't price lower)
    iv_series = np.maximum(iv_series, 0.30)

    return iv_series


def apply_bid_ask_slippage(theoretical_price: float, spread_pct: float) -> float:
    """Apply bid-ask spread cost to get realistic fill price when selling.

    When selling options, you receive the bid, which is below mid.
    """
    return theoretical_price * (1.0 - spread_pct / 2.0)
