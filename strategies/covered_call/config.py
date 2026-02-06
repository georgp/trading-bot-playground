from dataclasses import dataclass, field


@dataclass
class CoveredCallConfig:
    ticker: str = "NXDR"
    shares: int = 1000
    # Strike selection
    min_strike: float = 2.50
    strike_candidates: list[float] = field(
        default_factory=lambda: [2.00, 2.50, 3.00, 3.50, 4.00, 5.00]
    )
    # Expiration preferences (calendar days)
    target_dte: int = 30  # target ~monthly
    min_dte: int = 14
    max_dte: int = 45
    # Roll logic
    roll_dte_threshold: int = 5  # roll when <= 5 DTE remaining
    roll_profit_pct: float = 0.80  # roll if 80%+ of max profit captured
    # Costs
    commission_per_contract: float = 0.65
    bid_ask_spread_pct: float = 0.15  # 15% of mid price lost to spread
    # Risk
    risk_free_rate: float = 0.045  # ~4.5% current rates
    # Cash floor thesis
    net_cash_per_share: float = 1.50  # estimated net cash floor
    cash_burn_per_quarter: float = 0.10  # estimated cash burn per share/quarter
    # Position sizing
    max_portfolio_pct: float = 0.10  # max 10% of portfolio in this name
