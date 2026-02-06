"""Cash floor monitor -- tracks the fundamental thesis that NXDR trades near cash value."""

from dataclasses import dataclass
from datetime import date


@dataclass
class CashFloorSnapshot:
    date: date
    stock_price: float
    estimated_net_cash_per_share: float
    market_cap_to_cash_ratio: float
    thesis_intact: bool
    warning: str | None


class CashFloorMonitor:
    """Monitors whether the 'trading near cash value' thesis remains valid.

    The thesis: NXDR has limited downside because market cap ~ net cash.
    This monitor tracks the erosion of that floor over time due to cash burn
    and flags when the thesis breaks down.
    """

    def __init__(
        self,
        initial_net_cash_per_share: float = 1.50,
        quarterly_burn_per_share: float = 0.10,
        warning_ratio: float = 1.5,  # warn if price > 1.5x cash
        danger_ratio: float = 0.8,  # danger if cash drops below 80% of price
    ):
        self.initial_net_cash = initial_net_cash_per_share
        self.quarterly_burn = quarterly_burn_per_share
        self.warning_ratio = warning_ratio
        self.danger_ratio = danger_ratio
        self.snapshots: list[CashFloorSnapshot] = []

    def estimate_cash_at_date(self, start_date: date, current_date: date) -> float:
        """Estimate net cash per share at a given date, accounting for burn."""
        quarters_elapsed = (current_date - start_date).days / 90.0
        return max(
            self.initial_net_cash - self.quarterly_burn * quarters_elapsed,
            0.0,
        )

    def check(
        self, current_date: date, stock_price: float, start_date: date
    ) -> CashFloorSnapshot:
        """Check the cash floor thesis on a given date."""
        est_cash = self.estimate_cash_at_date(start_date, current_date)

        if est_cash > 0:
            ratio = stock_price / est_cash
        else:
            ratio = float("inf")

        warning = None
        thesis_intact = True

        if est_cash <= 0:
            warning = "CRITICAL: Estimated net cash has been fully burned"
            thesis_intact = False
        elif ratio > self.warning_ratio:
            warning = (
                f"Stock (${stock_price:.2f}) trading at {ratio:.1f}x "
                f"estimated cash (${est_cash:.2f}). "
                "Downside protection thesis weakened."
            )
        elif stock_price < est_cash * self.danger_ratio:
            warning = (
                f"Stock (${stock_price:.2f}) trading BELOW estimated cash "
                f"(${est_cash:.2f}). Potential deep value or thesis broken."
            )

        if est_cash < self.initial_net_cash * 0.5:
            warning = (
                f"Cash burn alert: estimated cash ${est_cash:.2f} is "
                f"<50% of initial ${self.initial_net_cash:.2f}"
            )
            thesis_intact = False

        snapshot = CashFloorSnapshot(
            date=current_date,
            stock_price=stock_price,
            estimated_net_cash_per_share=est_cash,
            market_cap_to_cash_ratio=ratio,
            thesis_intact=thesis_intact,
            warning=warning,
        )
        self.snapshots.append(snapshot)
        return snapshot
