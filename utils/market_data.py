"""Fetch historical stock data directly from Yahoo Finance (no yfinance dependency)."""

import json
from datetime import date, datetime, timedelta
from io import StringIO

import pandas as pd
import requests


def fetch_yahoo_history(
    ticker: str, start: date, end: date
) -> pd.DataFrame:
    """Fetch daily OHLCV from Yahoo Finance chart API.

    Returns DataFrame with DatetimeIndex and columns: Open, High, Low, Close, Volume
    """
    # Convert dates to Unix timestamps
    start_ts = int(datetime.combine(start, datetime.min.time()).timestamp())
    end_ts = int(datetime.combine(end, datetime.max.time()).timestamp())

    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
        f"?period1={start_ts}&period2={end_ts}&interval=1d"
        f"&includeAdjustedClose=true"
    )

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
    }

    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    chart = data["chart"]["result"][0]
    timestamps = chart["timestamp"]
    quotes = chart["indicators"]["quote"][0]

    df = pd.DataFrame(
        {
            "Open": quotes["open"],
            "High": quotes["high"],
            "Low": quotes["low"],
            "Close": quotes["close"],
            "Volume": quotes["volume"],
        },
        index=pd.to_datetime(timestamps, unit="s").normalize(),
    )
    df.index.name = "Date"
    df = df.dropna(subset=["Close"])
    return df
