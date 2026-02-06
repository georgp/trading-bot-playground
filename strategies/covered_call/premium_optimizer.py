"""Premium optimizer -- evaluates strike/expiration combos to maximize risk-adjusted income."""

from dataclasses import dataclass
import numpy as np

from .pricing import black_scholes_call, call_delta, call_theta, apply_bid_ask_slippage
from .config import CoveredCallConfig


@dataclass
class StrikeAnalysis:
    strike: float
    dte: int
    theoretical_premium: float
    net_premium: float  # after bid-ask slippage
    delta: float
    theta_daily: float
    annualized_return: float  # premium / stock_price annualized
    upside_to_strike_pct: float
    score: float


class PremiumOptimizer:
    """Finds the optimal strike/expiration combo for selling covered calls."""

    def __init__(self, config: CoveredCallConfig | None = None):
        self.config = config or CoveredCallConfig()

    def analyze_strike(
        self,
        stock_price: float,
        strike: float,
        dte: int,
        iv: float,
    ) -> StrikeAnalysis:
        """Analyze a single strike/expiration combination."""
        T = dte / 365.0
        r = self.config.risk_free_rate

        premium = black_scholes_call(stock_price, strike, T, r, iv)
        net_premium = apply_bid_ask_slippage(premium, self.config.bid_ask_spread_pct)
        delta = call_delta(stock_price, strike, T, r, iv)
        theta = call_theta(stock_price, strike, T, r, iv)
        annualized = (net_premium / stock_price) * (365.0 / dte) if dte > 0 else 0.0
        upside = (strike - stock_price) / stock_price

        # Composite score: balance premium income vs assignment risk
        # Higher is better
        if net_premium < 0.005:
            score = 0.0
        else:
            income_score = annualized
            # Prefer delta between 0.15-0.30 (sweet spot for covered calls)
            delta_score = 1.0 - abs(delta - 0.20) * 3.0
            delta_score = max(delta_score, 0.1)
            # Prefer having upside room
            upside_score = min(upside / 0.30, 1.0)
            score = income_score * 0.5 + delta_score * 0.3 + upside_score * 0.2

        return StrikeAnalysis(
            strike=strike,
            dte=dte,
            theoretical_premium=premium,
            net_premium=net_premium,
            delta=delta,
            theta_daily=theta,
            annualized_return=annualized,
            upside_to_strike_pct=upside,
            score=score,
        )

    def find_optimal(
        self,
        stock_price: float,
        iv: float,
        dte_options: list[int] | None = None,
    ) -> list[StrikeAnalysis]:
        """Evaluate all strike/DTE combos and return sorted by score."""
        if dte_options is None:
            dte_options = [14, 21, 30, 45]

        results = []
        for strike in self.config.strike_candidates:
            if strike <= stock_price * 1.02:
                continue
            for dte in dte_options:
                analysis = self.analyze_strike(stock_price, strike, dte, iv)
                if analysis.net_premium >= 0.01:
                    results.append(analysis)

        results.sort(key=lambda x: x.score, reverse=True)
        return results

    def format_analysis(
        self, stock_price: float, iv: float, top_n: int = 10
    ) -> str:
        """Return a formatted string with the top strike/DTE recommendations."""
        results = self.find_optimal(stock_price, iv)[:top_n]

        lines = [
            f"Premium Optimization for ${stock_price:.2f} (IV: {iv:.1%})",
            f"{'Strike':>8} {'DTE':>5} {'Premium':>9} {'Net':>9} "
            f"{'Delta':>7} {'Ann.Ret':>9} {'Upside':>8} {'Score':>7}",
            "-" * 72,
        ]

        for r in results:
            lines.append(
                f"${r.strike:>6.2f} {r.dte:>5d} ${r.theoretical_premium:>7.4f} "
                f"${r.net_premium:>7.4f} {r.delta:>7.3f} {r.annualized_return:>8.1%} "
                f"{r.upside_to_strike_pct:>7.1%} {r.score:>7.3f}"
            )

        return "\n".join(lines)
