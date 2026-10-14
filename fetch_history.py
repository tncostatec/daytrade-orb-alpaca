"""Baixa barras de 5 minutos (feed IEX, gratuito) e salva CSV por símbolo."""
import sys
from datetime import datetime, timedelta, timezone

import pandas as pd
from alpaca.data.enums import DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

from config import API_KEY, DATA_DIR, SECRET_KEY, SYMBOLS

YEARS = float(sys.argv[1]) if len(sys.argv) > 1 else 2.0

client = StockHistoricalDataClient(API_KEY, SECRET_KEY)
end = datetime.now(timezone.utc) - timedelta(minutes=20)
start = end - timedelta(days=int(365 * YEARS))

for sym in SYMBOLS:
    req = StockBarsRequest(
        symbol_or_symbols=sym,
        timeframe=TimeFrame(5, TimeFrameUnit.Minute),
        start=start,
        end=end,
        feed=DataFeed.IEX,
    )
    bars = client.get_stock_bars(req).df
    if bars.empty:
        print(f"{sym}: sem dados")
        continue
    df = bars.xs(sym, level="symbol").reset_index()
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True).dt.tz_convert("America/New_York")
    df = df[["timestamp", "open", "high", "low", "close", "volume"]]
    out = DATA_DIR / f"{sym}_5min.csv"
    df.to_csv(out, index=False)
    print(f"{sym}: {len(df)} barras  {df.timestamp.min():%Y-%m-%d} a {df.timestamp.max():%Y-%m-%d}  -> {out.name}")
