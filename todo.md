# NXDR Covered Call Strategy -- Project TODO

## Completed

- [x] **Black-Scholes pricing engine** (`strategies/covered_call/pricing.py`)
  - Call pricing, delta, theta
  - IV estimation from historical volatility (HV * 1.3x premium)
  - Bid-ask slippage model
- [x] **Core strategy engine** (`strategies/covered_call/strategy.py`)
  - Strike selection (score by annualized return penalized by delta)
  - Position management: open, sell call, check expiration, called-away re-entry
  - Roll logic: roll when <=5 DTE or >=80% profit captured
- [x] **Cash floor monitor** (`strategies/covered_call/cash_floor.py`)
  - Tracks estimated net cash per share over time with linear burn
  - Warns when price/cash ratio breaks threshold
- [x] **Premium optimizer** (`strategies/covered_call/premium_optimizer.py`)
  - Grid search across strike x DTE combos
  - Composite score: income (50%), delta sweet-spot (30%), upside room (20%)
- [x] **Backtesting engine** (`strategies/covered_call/backtest.py`)
  - Daily equity curve with mark-to-market on short calls
  - Sharpe, max drawdown, total/annualized return, premium yield
  - Head-to-head comparison of $2.00 vs $2.50 min strike
- [x] **Synthetic data fallback and 4-panel chart** (`run_backtest.py`)
- [x] **Initial backtest run** (synthetic data -- Yahoo blocked in sandbox)

## Known Issues to Fix

- [ ] **Roll logic is dead code in the backtest loop.** The `elif` on line 142 of
  `backtest.py` is unreachable -- the prior `if strategy.position is not None` block
  (line 127) catches the same condition. Rolls never fire during the backtest. Fix:
  restructure so expiration check and roll check are mutually exclusive based on
  whether expiration date has passed vs. not.
- [ ] **Negative net premiums on early trades.** When the stock is far below the
  strike and IV is low, the tiny theoretical premium doesn't cover commissions,
  resulting in negative "premium" trades (e.g., -$6.44). Add a minimum premium
  threshold: skip selling a call if net premium after spread + commissions < $0.
- [ ] **IV estimation is crude.** 20-day HV * 1.3 is a rough proxy. Real NXDR
  options IV could be very different. Need to validate this estimate or fetch
  actual IV data.

## Validation Tasks

### 1. Run with real market data
- [ ] Run `python run_backtest.py` locally where Yahoo Finance is accessible
- [ ] Compare synthetic results to real results -- how far off is the model?
- [ ] Record actual NXDR price range and volatility over the backtest period

### 2. Validate the cash floor thesis with real fundamentals
- [ ] Pull NXDR's actual balance sheet data (10-Q filings) for each quarter
  in the backtest period
- [ ] Calculate real net cash per share: (cash + short-term investments - total debt
  - operating lease liabilities) / shares outstanding
- [ ] Calculate actual quarterly cash burn from operating cash flow statements
- [ ] Replace the linear burn model in `CashFloorMonitor` with actual quarterly
  data points -- does the thesis hold or has cash eroded faster than assumed?
- [ ] Check for dilution: has share count increased (stock comp, offerings)?
  This lowers cash per share even without operational burn

### 3. Validate options pricing against reality
- [ ] Fetch actual NXDR options chains for several dates in the backtest period
  (use broker data or CBOE delayed quotes)
- [ ] Compare Black-Scholes theoretical prices to actual bid/ask quotes
- [ ] Measure real bid-ask spreads -- is 15% of mid realistic, or worse?
- [ ] Check open interest and volume: are there enough contracts to execute
  10-lot trades, or is the market too thin?
- [ ] If real options data shows spreads >25% of mid or open interest <50
  contracts, the strategy may not be practically executable

### 4. Stress test with adversarial price paths
- [ ] **Slow bleed scenario:** Stock drifts from $1.70 to $0.80 over 12 months.
  Cash floor thesis fails as cash burns. How bad is the P&L?
- [ ] **Gap down scenario:** Stock drops 40% overnight on an earnings miss.
  The cash floor doesn't help intraday. Measure the drawdown.
- [ ] **Whipsaw scenario:** Stock spikes above strike, gets called away, then
  immediately drops back. Measure the cost of re-entry at peak prices.
  (This already appeared in the $2.00 backtest -- quantify it more rigorously.)
- [ ] **IV crush scenario:** After a period of high vol, IV drops 50%.
  Premiums shrink. Is the strategy still worth the capital commitment?
- [ ] **Liquidity freeze:** Model what happens if you can't roll a position
  because no one is quoting options (spread = 100%). Force-hold to expiry.

### 5. Parameter sensitivity analysis
- [ ] Sweep min_strike from $1.50 to $4.00 in $0.25 increments. Plot total
  return, premium collected, times called away, and Sharpe for each.
- [ ] Sweep target_dte from 7 (weekly) to 60 (bi-monthly). Does shorter
  duration capture more theta, or do transaction costs eat the edge?
- [ ] Sweep bid_ask_spread_pct from 5% to 30%. At what spread level does
  the strategy become unprofitable vs. buy-and-hold?
- [ ] Sweep IV premium multiplier (currently 1.3x HV). How sensitive are
  results to IV estimation error?
- [ ] Test with commissions from $0 (some brokers) to $1.50/contract.

### 6. Compare to alternative strategies on the same thesis
- [ ] **Cash-secured puts at $1.50:** Sell puts below cash floor. If assigned,
  you're buying below cash value. Compare premium income and risk profile.
- [ ] **Collar (covered call + protective put):** Buy a $1.00 put alongside
  selling the $2.50 call. What does downside protection cost in net premium?
- [ ] **Diagonal spread:** Sell short-dated calls, buy longer-dated calls as
  a hedge. Does this reduce assignment risk while maintaining income?
- [ ] **Do nothing (just hold the stock):** Already tracked as "stock-only
  return." But also calculate risk-adjusted return (Sharpe) for comparison.
- [ ] **Sell the stock and buy T-bills:** At 4.5% risk-free, what's the
  opportunity cost of tying up capital in this name?

### 7. Execution / live-trading readiness
- [ ] Add a paper-trading mode that connects to a broker API (IBKR, Schwab)
  to place simulated orders and track real fills
- [ ] Build a daily cron job that checks: (a) any positions expiring within
  roll_dte_threshold, (b) current premium optimizer output, (c) cash floor
  status, and sends an alert
- [ ] Add portfolio-level position sizing: given total portfolio value,
  enforce the max_portfolio_pct cap
- [ ] Add an earnings date calendar check: never sell a call that spans an
  earnings date unless IV is sufficiently high to compensate

### 8. Code quality
- [ ] Add unit tests for Black-Scholes pricing (compare to known values)
- [ ] Add unit tests for strategy logic (expiration, called-away, roll)
- [ ] Add integration test: run backtest on a fixed synthetic seed and
  assert exact P&L numbers don't regress
- [ ] Type-check with mypy
- [ ] Lint with ruff
