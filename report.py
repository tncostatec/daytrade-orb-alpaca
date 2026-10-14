"""Acompanhamento da prova de uso: lê journal/trades.csv e compara com o backtest filtrado."""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from backtest_orb import START_EQUITY
from config import API_KEY, JOURNAL_DIR, SECRET_KEY

# Referência do backtest SPY ORB 15min 2R + filtro OR estreito, ano 2 (fora da amostra):
# 87 trades em ~250 pregões (35%), PF 1,63, R médio +0,31, taxa de acerto ~46%.
path = JOURNAL_DIR / "trades.csv"
if not path.exists():
    raise SystemExit("journal/trades.csv ainda não existe: nenhum pregão registrado.")

j = pd.read_csv(path)
n = len(j)
by_reason = j.reason.value_counts().to_dict()
tr = j[j.qty > 0].copy()
print(f"pregões registrados : {n}/20   {by_reason}")
if tr.empty:
    print("nenhuma operação executada ainda.")
    raise SystemExit
tr["risk"] = (tr.entry - tr.stop).abs() * tr.qty
tr["R"] = tr.pnl / tr.risk
wins, losses = tr[tr.pnl > 0], tr[tr.pnl <= 0]
pf = wins.pnl.sum() / abs(losses.pnl.sum()) if not losses.empty and losses.pnl.sum() != 0 else float("inf")
print(f"operações           : {len(tr)}  (long {int((tr.side == 1).sum())}, short {int((tr.side == -1).sum())})")
print(f"resultado líquido   : ${tr.pnl.sum():+,.2f}   melhor {tr.pnl.max():+,.2f}   pior {tr.pnl.min():+,.2f}")
print(f"taxa de acerto      : {len(wins) / len(tr) * 100:.0f}%   profit factor {pf:.2f}   R médio {tr.R.mean():+.2f}")
print(f"saídas              : {tr.reason.value_counts().to_dict()}")
if "exit" in tr and tr.exit.notna().any():
    slip = ((tr.exit - tr.stop).abs() * (tr.reason == "stop_or_target")).where(tr.exit.notna())
    print(f"desvio médio saída vs stop/alvo (só p/ auditoria): {slip.mean():.3f}")


def buy_and_hold(first, last, symbol="SPY"):
    """Compra na abertura do primeiro pregão da prova, segura até o fechamento do último."""
    from alpaca.data.enums import DataFeed
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame

    req = StockBarsRequest(symbol_or_symbols=symbol, timeframe=TimeFrame.Day, feed=DataFeed.IEX,
                           start=datetime.combine(first, datetime.min.time()),
                           end=datetime.combine(last + timedelta(days=1), datetime.min.time()))
    d = StockHistoricalDataClient(API_KEY, SECRET_KEY).get_stock_bars(req).df.reset_index()
    d["d"] = d.timestamp.dt.tz_convert("America/New_York").dt.date
    d = d[(d.d >= first) & (d.d <= last)]
    o, c = float(d.iloc[0].open), float(d.iloc[-1].close)
    ny = datetime.now(ZoneInfo("America/New_York"))
    parcial = d.iloc[-1].d == ny.date() and ny.hour < 16
    return o, c, d.iloc[0].d, d.iloc[-1].d, parcial


first, last = date.fromisoformat(j.date.min()), date.fromisoformat(j.date.max())
estr = tr.pnl.sum() / START_EQUITY * 100
try:
    o, c, d0, d1, parcial = buy_and_hold(first, last)
    bh = (c / o - 1) * 100
    nota = "  (ÚLTIMO DIA PARCIAL: mercado aberto)" if parcial else ""
    print(f"benchmark           : buy-and-hold SPY {d0:%d/%m} abertura {o:.2f} -> {d1:%d/%m} fecham. {c:.2f}{nota}")
    print(f"                      estratégia {estr:+.2f}% (${tr.pnl.sum():+,.2f})  vs  buy-and-hold "
          f"{bh:+.2f}% (${START_EQUITY * bh / 100:+,.2f})  sobre ${START_EQUITY:,.0f}")
    print("                      (buy-and-hold fica 100% exposto o tempo todo; a estratégia arrisca 0,5% por trade)")
except Exception as e:  # sem rede não pode derrubar o relatório
    print(f"benchmark           : indisponível ({type(e).__name__}: {str(e).strip().splitlines()[0] if str(e).strip() else ''})")
print("\n" + tr[["date", "side", "qty", "entry", "stop", "target", "exit", "pnl", "R", "reason"]].to_string(index=False))
