"""Core covered call strategy logic: position management and roll decisions."""

from dataclasses import dataclass
from datetime import date, timedelta
import numpy as np

from .config import CoveredCallConfig
from .pricing import (
    black_scholes_call,
    call_delta,
    apply_bid_ask_slippage,
)


@dataclass
class OptionPosition:
    strike: float
    expiration: date
    premium_received: float  # net of slippage/commissions
    contracts: int
    entry_date: date
    entry_stock_price: float


@dataclass
class TradeRecord:
    date: date
    action: str  # "SELL_CALL", "EXPIRE", "CALLED_AWAY", "ROLL", "BUY_STOCK"
    strike: float | None
    expiration: date | None
    premium: float  # positive = received, negative = paid
    stock_price: float
    shares: int
    details: str


class CoveredCallStrategy:
    def __init__(self, config: CoveredCallConfig | None = None):
        self.config = config or CoveredCallConfig()
        self.position: OptionPosition | None = None
        self.shares_held: int = 0
        self.trades: list[TradeRecord] = []
        self.total_premium_collected: float = 0.0
        self.total_commissions: float = 0.0
        self.times_called_away: int = 0

    def select_strike(
        self, stock_price: float, iv: float, dte: int
    ) -> tuple[float, float]:
        """Select the best strike price for a new call sale.

        Strategy: Among strikes >= min_strike, pick the one that maximizes
        premium per day of theta while maintaining a reasonable delta.

        Returns:
            (strike, theoretical_premium)
        """
        T = dte / 365.0
        best_strike = self.config.min_strike
        best_score = -1.0

        for strike in self.config.strike_candidates:
            if strike < self.config.min_strike:
                continue
            if strike <= stock_price * 1.02:
                # Skip strikes too close to/below current price
                # We want OTM calls for upside participation
                continue

            price = black_scholes_call(
                stock_price, strike, T, self.config.risk_free_rate, iv
            )
            delta = call_delta(
                stock_price, strike, T, self.config.risk_free_rate, iv
            )

            net_price = apply_bid_ask_slippage(price, self.config.bid_ask_spread_pct)

            if net_price < 0.01:
                continue  # not worth selling for less than a penny

            # Score: annualized premium return on capital at risk,
            # penalized by probability of assignment (delta)
            annualized_return = (net_price / stock_price) * (365.0 / dte)
            assignment_penalty = 1.0 - 0.5 * delta  # prefer lower delta
            score = annualized_return * assignment_penalty

            if score > best_score:
                best_score = score
                best_strike = strike

        premium = black_scholes_call(
            stock_price, best_strike, T, self.config.risk_free_rate, iv
        )
        return best_strike, premium

    def open_stock_position(
        self, current_date: date, stock_price: float
    ) -> TradeRecord:
        """Buy the initial stock position."""
        self.shares_held = self.config.shares
        trade = TradeRecord(
            date=current_date,
            action="BUY_STOCK",
            strike=None,
            expiration=None,
            premium=-stock_price * self.config.shares,
            stock_price=stock_price,
            shares=self.config.shares,
            details=f"Bought {self.config.shares} shares at ${stock_price:.2f}",
        )
        self.trades.append(trade)
        return trade

    def sell_call(
        self,
        current_date: date,
        stock_price: float,
        iv: float,
        dte: int | None = None,
    ) -> TradeRecord:
        """Sell a covered call against the stock position."""
        if dte is None:
            dte = self.config.target_dte

        strike, theoretical_premium = self.select_strike(stock_price, iv, dte)
        net_premium = apply_bid_ask_slippage(
            theoretical_premium, self.config.bid_ask_spread_pct
        )

        contracts = self.shares_held // 100
        commission = contracts * self.config.commission_per_contract
        total_premium = net_premium * contracts * 100 - commission

        expiration = current_date + timedelta(days=dte)

        self.position = OptionPosition(
            strike=strike,
            expiration=expiration,
            premium_received=total_premium,
            contracts=contracts,
            entry_date=current_date,
            entry_stock_price=stock_price,
        )

        self.total_premium_collected += total_premium
        self.total_commissions += commission

        trade = TradeRecord(
            date=current_date,
            action="SELL_CALL",
            strike=strike,
            expiration=expiration,
            premium=total_premium,
            stock_price=stock_price,
            shares=self.shares_held,
            details=(
                f"Sold {contracts}x ${strike:.2f}C "
                f"exp {expiration} for ${net_premium:.4f}/share "
                f"(total ${total_premium:.2f}, IV={iv:.1%})"
            ),
        )
        self.trades.append(trade)
        return trade

    def check_expiration(
        self, current_date: date, stock_price: float
    ) -> TradeRecord | None:
        """Check if current option position has expired."""
        if self.position is None:
            return None
        if current_date < self.position.expiration:
            return None

        if stock_price >= self.position.strike:
            # Called away -- shares sold at strike
            self.times_called_away += 1
            proceeds = self.position.strike * self.shares_held
            trade = TradeRecord(
                date=current_date,
                action="CALLED_AWAY",
                strike=self.position.strike,
                expiration=self.position.expiration,
                premium=0.0,
                stock_price=stock_price,
                shares=self.shares_held,
                details=(
                    f"Shares called away at ${self.position.strike:.2f} "
                    f"(stock at ${stock_price:.2f}). "
                    f"Proceeds: ${proceeds:.2f}"
                ),
            )
            self.shares_held = 0
            self.position = None
            self.trades.append(trade)
            return trade
        else:
            # Expired worthless -- keep shares
            trade = TradeRecord(
                date=current_date,
                action="EXPIRE",
                strike=self.position.strike,
                expiration=self.position.expiration,
                premium=0.0,
                stock_price=stock_price,
                shares=self.shares_held,
                details=(
                    f"Call ${self.position.strike:.2f} expired worthless "
                    f"(stock at ${stock_price:.2f}). Full premium kept."
                ),
            )
            self.position = None
            self.trades.append(trade)
            return trade

    def should_roll(
        self, current_date: date, stock_price: float, iv: float
    ) -> bool:
        """Determine if we should roll the current position early."""
        if self.position is None:
            return False

        days_remaining = (self.position.expiration - current_date).days

        # Roll if near expiration
        if days_remaining <= self.config.roll_dte_threshold:
            return True

        # Roll if we've captured most of the premium
        T = days_remaining / 365.0
        current_value = black_scholes_call(
            stock_price,
            self.position.strike,
            T,
            self.config.risk_free_rate,
            iv,
        )
        original_premium_per_share = (
            self.position.premium_received / (self.position.contracts * 100)
        )
        profit_captured = original_premium_per_share - current_value

        if profit_captured >= original_premium_per_share * self.config.roll_profit_pct:
            return True

        return False

    def roll_position(
        self, current_date: date, stock_price: float, iv: float
    ) -> list[TradeRecord]:
        """Roll: buy back current call, sell new one."""
        trades = []

        if self.position is not None:
            # Buy back the current call
            days_remaining = (self.position.expiration - current_date).days
            T = max(days_remaining / 365.0, 0.001)
            buyback_price = black_scholes_call(
                stock_price,
                self.position.strike,
                T,
                self.config.risk_free_rate,
                iv,
            )
            # When buying, we pay the ask (above mid)
            buyback_cost = buyback_price * (1.0 + self.config.bid_ask_spread_pct / 2.0)
            contracts = self.position.contracts
            commission = contracts * self.config.commission_per_contract
            total_cost = buyback_cost * contracts * 100 + commission

            self.total_commissions += commission

            trade = TradeRecord(
                date=current_date,
                action="ROLL",
                strike=self.position.strike,
                expiration=self.position.expiration,
                premium=-total_cost,
                stock_price=stock_price,
                shares=self.shares_held,
                details=(
                    f"Bought back {contracts}x ${self.position.strike:.2f}C "
                    f"for ${buyback_cost:.4f}/share (cost ${total_cost:.2f})"
                ),
            )
            trades.append(trade)
            self.trades.append(trade)
            self.position = None

        # Sell new call
        sell_trade = self.sell_call(current_date, stock_price, iv)
        trades.append(sell_trade)

        return trades
