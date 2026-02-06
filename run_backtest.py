#!/usr/bin/env python3
"""Run the NXDR covered call strategy backtest."""

import sys
from datetime import date, timedelta

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd
from utils.market_data import fetch_yahoo_history

from strategies.covered_call import (
    CoveredCallBacktest,
    PremiumOptimizer,
    CashFloorMonitor,
)
from strategies.covered_call.config import CoveredCallConfig
from strategies.covered_call.backtest import format_backtest_report


def fetch_data(ticker: str, start: str, end: str) -> pd.DataFrame:
    """Fetch historical data from Yahoo Finance."""
    print(f"Fetching {ticker} data from {start} to {end}...")
    start_date = date.fromisoformat(start)
    end_date = date.fromisoformat(end)
    data = fetch_yahoo_history(ticker, start_date, end_date)
    if data.empty:
        raise RuntimeError(f"No data returned for {ticker}")
    print(f"  Got {len(data)} trading days")
    return data


def plot_results(result, output_path: str = "backtest_results.png"):
    """Generate a multi-panel chart of backtest results."""
    df = result.daily_equity
    dates = pd.to_datetime(df["Date"])

    fig, axes = plt.subplots(4, 1, figsize=(14, 16), sharex=True)
    fig.suptitle("NXDR Covered Call Strategy Backtest", fontsize=16, fontweight="bold")

    # Panel 1: Equity curve vs stock-only
    ax1 = axes[0]
    initial_equity = df["Equity"].iloc[0]
    initial_stock = df["StockPrice"].iloc[0]
    shares = initial_equity / initial_stock  # equivalent shares for comparison

    ax1.plot(dates, df["Equity"], label="Covered Call Strategy", linewidth=2, color="blue")
    ax1.plot(
        dates,
        df["StockPrice"] * shares,
        label="Buy & Hold (same capital)",
        linewidth=1.5,
        color="gray",
        linestyle="--",
    )
    ax1.set_ylabel("Portfolio Value ($)")
    ax1.legend(loc="upper left")
    ax1.set_title("Equity Curve")
    ax1.grid(True, alpha=0.3)

    # Panel 2: Stock price with call strikes overlaid
    ax2 = axes[1]
    ax2.plot(dates, df["StockPrice"], color="black", linewidth=1.5, label="NXDR Price")

    # Mark call sales and expirations
    for trade in result.trades:
        trade_date = pd.Timestamp(trade.date)
        if trade.action == "SELL_CALL" and trade.strike:
            ax2.axhline(
                y=trade.strike,
                xmin=0,
                xmax=1,
                color="red",
                alpha=0.15,
                linewidth=0.5,
            )
            ax2.plot(trade_date, trade.stock_price, "rv", markersize=6)
        elif trade.action == "CALLED_AWAY":
            ax2.plot(trade_date, trade.stock_price, "g^", markersize=10)
        elif trade.action == "EXPIRE":
            ax2.plot(trade_date, trade.stock_price, "bo", markersize=4)

    ax2.set_ylabel("Stock Price ($)")
    ax2.set_title("Price Action & Trades (v=sell call, ^=called away, o=expire)")
    ax2.grid(True, alpha=0.3)

    # Panel 3: Implied volatility
    ax3 = axes[2]
    ax3.fill_between(dates, df["IV"] * 100, alpha=0.3, color="purple")
    ax3.plot(dates, df["IV"] * 100, color="purple", linewidth=1)
    ax3.set_ylabel("Estimated IV (%)")
    ax3.set_title("Implied Volatility (estimated from historical)")
    ax3.grid(True, alpha=0.3)

    # Panel 4: Cumulative premium collected
    ax4 = axes[3]
    cumulative_premium = []
    running = 0.0
    premium_dates = []
    for trade in result.trades:
        if trade.action == "SELL_CALL":
            running += trade.premium
            premium_dates.append(pd.Timestamp(trade.date))
            cumulative_premium.append(running)
    if premium_dates:
        ax4.step(premium_dates, cumulative_premium, where="post", color="green", linewidth=2)
        ax4.fill_between(
            premium_dates, cumulative_premium, step="post", alpha=0.2, color="green"
        )
    ax4.set_ylabel("Cumulative Premium ($)")
    ax4.set_title("Premium Income Over Time")
    ax4.grid(True, alpha=0.3)

    ax4.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax4.xaxis.set_major_locator(mdates.MonthLocator())
    plt.xticks(rotation=45)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    print(f"\nChart saved to {output_path}")


def run_current_analysis(stock_price: float, iv: float):
    """Run the premium optimizer for current market conditions."""
    config = CoveredCallConfig()
    optimizer = PremiumOptimizer(config)

    print("\n")
    print("=" * 70)
    print("  CURRENT MARKET ANALYSIS")
    print("=" * 70)
    print(optimizer.format_analysis(stock_price, iv))
    print()


def main():
    # Configuration
    config = CoveredCallConfig(
        ticker="NXDR",
        shares=1000,
        min_strike=2.00,  # also consider $2.00 strikes for more premium
        strike_candidates=[2.00, 2.50, 3.00, 3.50, 4.00, 5.00],
        target_dte=30,
        roll_dte_threshold=5,
        roll_profit_pct=0.80,
        bid_ask_spread_pct=0.15,
        risk_free_rate=0.045,
        net_cash_per_share=1.50,
        cash_burn_per_quarter=0.10,
    )

    # Date range: last year
    end_date = date.today()
    start_date = end_date - timedelta(days=365)

    # We need extra data before start for IV warmup
    warmup_start = start_date - timedelta(days=60)

    # Fetch data
    try:
        prices = fetch_data(
            config.ticker,
            warmup_start.isoformat(),
            end_date.isoformat(),
        )
    except Exception as e:
        print(f"Error fetching data: {e}")
        print("Falling back to synthetic data for demonstration...")
        prices = generate_synthetic_data(start_date, end_date)

    # Run backtest
    print("\nRunning backtest...")
    bt = CoveredCallBacktest(config)
    result = bt.run(prices, start_date=start_date, end_date=end_date)

    # Print report
    report = format_backtest_report(result)
    print(report)

    # Generate chart
    try:
        plot_results(result, "backtest_results.png")
    except Exception as e:
        print(f"Warning: Could not generate chart: {e}")

    # Run current market analysis
    current_price = prices["Close"].iloc[-1]
    if hasattr(current_price, "item"):
        current_price = current_price.item()
    current_iv = result.daily_equity["IV"].iloc[-1]
    run_current_analysis(current_price, current_iv)

    # Also run with $2.50 min strike for comparison
    print("\n" + "=" * 70)
    print("  COMPARISON: $2.50 MINIMUM STRIKE")
    print("=" * 70)
    config_conservative = CoveredCallConfig(
        ticker="NXDR",
        shares=1000,
        min_strike=2.50,
        strike_candidates=[2.50, 3.00, 3.50, 4.00, 5.00],
        target_dte=30,
        bid_ask_spread_pct=0.15,
        risk_free_rate=0.045,
        net_cash_per_share=1.50,
        cash_burn_per_quarter=0.10,
    )
    bt_conservative = CoveredCallBacktest(config_conservative)
    result_conservative = bt_conservative.run(
        prices, start_date=start_date, end_date=end_date
    )
    report_conservative = format_backtest_report(result_conservative)
    print(report_conservative)

    print("\n" + "=" * 70)
    print("  HEAD-TO-HEAD COMPARISON")
    print("=" * 70)
    print(f"  {'Metric':<30} {'$2.00 Min':>15} {'$2.50 Min':>15}")
    print(f"  {'-'*30} {'-'*15} {'-'*15}")
    print(
        f"  {'Total Return':<30} {result.total_return_pct:>14.2f}% "
        f"{result_conservative.total_return_pct:>14.2f}%"
    )
    print(
        f"  {'Premium Collected':<30} ${result.total_premium_collected:>13.2f} "
        f"${result_conservative.total_premium_collected:>13.2f}"
    )
    print(
        f"  {'Times Called Away':<30} {result.times_called_away:>15d} "
        f"{result_conservative.times_called_away:>15d}"
    )
    print(
        f"  {'Max Drawdown':<30} {result.max_drawdown_pct:>14.2f}% "
        f"{result_conservative.max_drawdown_pct:>14.2f}%"
    )
    print(
        f"  {'Sharpe Ratio':<30} {result.sharpe_ratio:>15.2f} "
        f"{result_conservative.sharpe_ratio:>15.2f}"
    )
    print(
        f"  {'Stock-Only Return':<30} {result.stock_only_return_pct:>14.2f}%"
    )
    print()

    return result


def generate_synthetic_data(
    start_date: date, end_date: date
) -> pd.DataFrame:
    """Generate synthetic NXDR-like price data if real data unavailable.

    Models a stock around $1.50-$2.50 range with high volatility typical
    of small-cap tech.
    """
    import numpy as np

    np.random.seed(42)

    # Include warmup period
    warmup_start = start_date - timedelta(days=60)
    days = (end_date - warmup_start).days
    trading_days = int(days * 252 / 365)

    # GBM with mean-reverting component around $1.80
    dt = 1 / 252
    mu = 0.05  # slight upward drift
    sigma = 0.65  # high vol for small cap
    mean_level = 1.80
    mean_revert_speed = 2.0

    prices = [1.70]
    for _ in range(trading_days - 1):
        S = prices[-1]
        drift = mean_revert_speed * (mean_level - S) * dt + mu * dt
        shock = sigma * np.sqrt(dt) * np.random.randn()
        S_new = S * np.exp(drift + shock)
        S_new = max(S_new, 0.50)  # floor at $0.50
        prices.append(S_new)

    date_range = pd.bdate_range(start=warmup_start, periods=trading_days)
    df = pd.DataFrame({"Close": prices}, index=date_range)
    df.index.name = "Date"
    return df


if __name__ == "__main__":
    main()
