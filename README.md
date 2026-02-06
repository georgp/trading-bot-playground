# trading-bot-playground

Trading strategy research and backtesting.

## Strategies

### NXDR Covered Call (`strategies/covered_call/`)

Sell covered calls on NXDR (Nextdoor) based on the thesis that it trades near cash value, providing a downside floor while premiums generate income.

**Components:**
- `config.py` -- Strategy parameters (strikes, DTE, costs, cash floor estimates)
- `pricing.py` -- Black-Scholes options pricing, delta, theta, IV estimation
- `strategy.py` -- Core strategy: strike selection, position management, roll logic
- `cash_floor.py` -- Monitors the "trading near cash value" thesis over time
- `premium_optimizer.py` -- Evaluates strike/expiration combos for best risk-adjusted income
- `backtest.py` -- Full backtesting engine with equity tracking and reporting

**Run:**
```bash
pip install -r requirements.txt
python run_backtest.py
```

Generates a backtest report and `backtest_results.png` chart.
