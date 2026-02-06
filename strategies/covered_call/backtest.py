"""Backtesting engine for the covered call strategy."""

from dataclasses import dataclass, field
from datetime import date, timedelta
import numpy as np
import pandas as pd

from .config import CoveredCallConfig
from .strategy import CoveredCallStrategy, TradeRecord
from .pricing import implied_volatility_from_history
from .cash_floor import CashFloorMonitor
from .premium_optimizer import PremiumOptimizer


@dataclass
class BacktestResult:
    # Returns
    total_return_pct: float
    annualized_return_pct: float
    stock_only_return_pct: float
    excess_return_pct: float  # strategy vs buy-and-hold
    # Premium income
    total_premium_collected: float
    total_commissions: float
    net_premium: float
    premium_yield_pct: float  # premium / initial investment
    # Risk
    max_drawdown_pct: float
    sharpe_ratio: float
    # Activity
    num_trades: int
    times_called_away: int
    avg_days_per_cycle: float
    # Data
    trades: list[TradeRecord]
    daily_equity: pd.DataFrame
    cash_floor_warnings: list[str]


class CoveredCallBacktest:
    """Runs a historical backtest of the covered call strategy."""

    def __init__(self, config: CoveredCallConfig | None = None):
        self.config = config or CoveredCallConfig()

    def run(
        self,
        prices: pd.DataFrame,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> BacktestResult:
        """Run the backtest on historical price data.

        Args:
            prices: DataFrame with 'Date' and 'Close' columns (or DatetimeIndex)
            start_date: Backtest start date
            end_date: Backtest end date

        Returns:
            BacktestResult with all metrics
        """
        # Normalize the dataframe: always produce columns [Date, Close] with no index ambiguity
        if isinstance(prices.index, pd.DatetimeIndex):
            df = pd.DataFrame({
                "Date": prices.index.date,
                "Close": prices["Close"].values,
            })
        elif "Date" in prices.columns:
            df = pd.DataFrame({
                "Date": pd.to_datetime(prices["Date"]).dt.date,
                "Close": prices["Close"].values,
            })
        else:
            df = prices[["Close"]].copy().reset_index()
            df.columns = ["Date", "Close"]
            df["Date"] = pd.to_datetime(df["Date"]).dt.date

        df = df.sort_values("Date").reset_index(drop=True)

        if start_date:
            df = df[df["Date"] >= start_date]
        if end_date:
            df = df[df["Date"] <= end_date]
        df = df.reset_index(drop=True)

        if len(df) < 30:
            raise ValueError("Need at least 30 trading days for backtest")

        # Calculate implied volatility estimates
        close_prices = df["Close"].values
        iv_series = implied_volatility_from_history(close_prices, window=20)

        # Initialize strategy components
        strategy = CoveredCallStrategy(self.config)
        cash_monitor = CashFloorMonitor(
            initial_net_cash_per_share=self.config.net_cash_per_share,
            quarterly_burn_per_share=self.config.cash_burn_per_quarter,
        )

        # State tracking -- cash starts at the capital needed to buy shares
        # so equity = cash + stock_value - option_liability = initial_investment on day 0
        first_price = df["Close"].iloc[0]
        initial_investment = first_price * self.config.shares
        cash = initial_investment
        equity_curve = []
        cash_warnings = []
        backtest_start = df["Date"].iloc[0]

        for i, row in df.iterrows():
            current_date = row["Date"]
            stock_price = row["Close"]
            iv = iv_series[i] if not np.isnan(iv_series[i]) else 0.50

            # Day 0: buy stock and sell first call
            if strategy.shares_held == 0 and strategy.position is None:
                if i == 0 or strategy.times_called_away > 0:
                    # Buy stock
                    buy_trade = strategy.open_stock_position(current_date, stock_price)
                    cost = stock_price * self.config.shares
                    cash -= cost

                    # Sell first call
                    sell_trade = strategy.sell_call(current_date, stock_price, iv)
                    cash += sell_trade.premium

            # Check for expiration
            if strategy.position is not None:
                exp_trade = strategy.check_expiration(current_date, stock_price)
                if exp_trade is not None:
                    if exp_trade.action == "CALLED_AWAY":
                        # Receive strike price * shares
                        cash += strategy.config.shares * exp_trade.strike
                        # Re-buy shares and sell new call on next iteration
                    # If expired worthless, just sell a new call
                    if exp_trade.action == "EXPIRE":
                        sell_trade = strategy.sell_call(
                            current_date, stock_price, iv
                        )
                        cash += sell_trade.premium

            # Check for early roll opportunity
            elif strategy.position is not None:
                if strategy.should_roll(current_date, stock_price, iv):
                    roll_trades = strategy.roll_position(
                        current_date, stock_price, iv
                    )
                    for t in roll_trades:
                        cash += t.premium

            # Cash floor check (weekly)
            if i % 5 == 0:
                snapshot = cash_monitor.check(
                    current_date, stock_price, backtest_start
                )
                if snapshot.warning:
                    cash_warnings.append(f"[{current_date}] {snapshot.warning}")

            # Calculate daily equity
            stock_value = strategy.shares_held * stock_price
            # Mark-to-market the short call
            option_liability = 0.0
            if strategy.position is not None:
                days_remaining = (strategy.position.expiration - current_date).days
                if days_remaining > 0:
                    T = days_remaining / 365.0
                    option_liability = (
                        black_scholes_call_for_mtm(
                            stock_price,
                            strategy.position.strike,
                            T,
                            self.config.risk_free_rate,
                            iv,
                        )
                        * strategy.position.contracts
                        * 100
                    )

            total_equity = cash + stock_value - option_liability
            equity_curve.append(
                {
                    "Date": current_date,
                    "Equity": total_equity,
                    "StockPrice": stock_price,
                    "Cash": cash,
                    "StockValue": stock_value,
                    "OptionLiability": option_liability,
                    "IV": iv,
                }
            )

        equity_df = pd.DataFrame(equity_curve)

        # Calculate metrics
        final_equity = equity_df["Equity"].iloc[-1]
        total_return_pct = (final_equity / initial_investment - 1) * 100

        trading_days = len(equity_df)
        annualized_return = (
            (final_equity / initial_investment) ** (252 / trading_days) - 1
        ) * 100

        first_price = df["Close"].iloc[0]
        last_price = df["Close"].iloc[-1]
        stock_only_return = (last_price / first_price - 1) * 100

        # Max drawdown
        equity_values = equity_df["Equity"].values
        running_max = np.maximum.accumulate(equity_values)
        drawdowns = (equity_values - running_max) / running_max
        max_drawdown = drawdowns.min() * 100

        # Sharpe ratio (annualized)
        daily_returns = np.diff(equity_values) / equity_values[:-1]
        if len(daily_returns) > 1 and np.std(daily_returns) > 0:
            sharpe = (
                np.mean(daily_returns) / np.std(daily_returns) * np.sqrt(252)
            )
        else:
            sharpe = 0.0

        # Average cycle length
        sell_dates = [
            t.date for t in strategy.trades if t.action == "SELL_CALL"
        ]
        if len(sell_dates) > 1:
            cycle_days = [
                (sell_dates[i + 1] - sell_dates[i]).days
                for i in range(len(sell_dates) - 1)
            ]
            avg_cycle = np.mean(cycle_days)
        else:
            avg_cycle = 0.0

        return BacktestResult(
            total_return_pct=total_return_pct,
            annualized_return_pct=annualized_return,
            stock_only_return_pct=stock_only_return,
            excess_return_pct=total_return_pct - stock_only_return,
            total_premium_collected=strategy.total_premium_collected,
            total_commissions=strategy.total_commissions,
            net_premium=strategy.total_premium_collected - strategy.total_commissions,
            premium_yield_pct=(strategy.total_premium_collected / initial_investment)
            * 100,
            max_drawdown_pct=max_drawdown,
            sharpe_ratio=sharpe,
            num_trades=len(strategy.trades),
            times_called_away=strategy.times_called_away,
            avg_days_per_cycle=avg_cycle,
            trades=strategy.trades,
            daily_equity=equity_df,
            cash_floor_warnings=cash_warnings,
        )


def black_scholes_call_for_mtm(S, K, T, r, sigma):
    """Wrapper to avoid circular import for mark-to-market."""
    from .pricing import black_scholes_call

    return black_scholes_call(S, K, T, r, sigma)


def format_backtest_report(result: BacktestResult) -> str:
    """Format the backtest results into a readable report."""
    lines = [
        "=" * 70,
        "  NXDR COVERED CALL STRATEGY -- BACKTEST REPORT",
        "=" * 70,
        "",
        "PERFORMANCE SUMMARY",
        "-" * 40,
        f"  Total Return:          {result.total_return_pct:>8.2f}%",
        f"  Annualized Return:     {result.annualized_return_pct:>8.2f}%",
        f"  Stock-Only Return:     {result.stock_only_return_pct:>8.2f}%",
        f"  Excess Return (alpha): {result.excess_return_pct:>8.2f}%",
        "",
        "PREMIUM INCOME",
        "-" * 40,
        f"  Total Premium:         ${result.total_premium_collected:>10.2f}",
        f"  Total Commissions:     ${result.total_commissions:>10.2f}",
        f"  Net Premium:           ${result.net_premium:>10.2f}",
        f"  Premium Yield:         {result.premium_yield_pct:>8.2f}%",
        "",
        "RISK METRICS",
        "-" * 40,
        f"  Max Drawdown:          {result.max_drawdown_pct:>8.2f}%",
        f"  Sharpe Ratio:          {result.sharpe_ratio:>8.2f}",
        "",
        "ACTIVITY",
        "-" * 40,
        f"  Total Trades:          {result.num_trades:>8d}",
        f"  Times Called Away:     {result.times_called_away:>8d}",
        f"  Avg Days per Cycle:    {result.avg_days_per_cycle:>8.1f}",
        "",
    ]

    if result.cash_floor_warnings:
        lines.append("CASH FLOOR WARNINGS")
        lines.append("-" * 40)
        for w in result.cash_floor_warnings:
            lines.append(f"  {w}")
        lines.append("")

    lines.append("TRADE LOG")
    lines.append("-" * 40)
    for t in result.trades:
        lines.append(f"  [{t.date}] {t.details}")

    lines.append("")
    lines.append("=" * 70)
    return "\n".join(lines)
