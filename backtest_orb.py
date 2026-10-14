"""Opening Range Breakout (ORB) intradiário, com custos e sizing por risco.

Regras:
- Range de abertura = máxima/mínima dos primeiros OR_MIN minutos (09:30 ET).
- Primeiro fechamento de barra acima do range -> compra na abertura da próxima barra.
  Primeiro fechamento abaixo -> venda a descoberto. Uma operação por dia.
- Stop no lado oposto do range. Alvo = TARGET_R vezes o risco.
- Sem alvo/stop até EXIT_TIME, encerra a mercado na abertura dessa barra.
- Se stop e alvo caem na mesma barra, assume stop (conservador).
- Slippage SLIP por lado por ação. Comissão zero (Alpaca).
- Tamanho: RISK_PCT do patrimônio por operação, sem alavancagem.
"""
import sys

import numpy as np
import pandas as pd

from config import DATA_DIR, SYMBOLS

OR_MIN = 15          # minutos do range de abertura
TARGET_R = 2.0       # alvo em múltiplos do risco
EXIT_TIME = "15:55"  # ET
SLIP = 0.01          # $/ação por lado
RISK_PCT = 0.005     # 0,5% do patrimônio por operação
START_EQUITY = 100_000.0


def load(sym):
    df = pd.read_csv(DATA_DIR / f"{sym}_5min.csv", parse_dates=["timestamp"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True).dt.tz_convert("America/New_York")
    t = df["timestamp"].dt.strftime("%H:%M")
    df = df[(t >= "09:30") & (t < "16:00")].copy()
    df["date"] = df["timestamp"].dt.date
    df["hm"] = df["timestamp"].dt.strftime("%H:%M")
    return df


def run(sym, or_min=OR_MIN, target_r=TARGET_R, df=None):
    if df is None:
        df = load(sym)
    equity = START_EQUITY
    trades = []
    n_or = or_min // 5
    for date, day in df.groupby("date", sort=True):
        day = day.reset_index(drop=True)
        if len(day) < n_or + 3 or day.loc[0, "hm"] != "09:30":
            continue
        orh = day.loc[: n_or - 1, "high"].max()
        orl = day.loc[: n_or - 1, "low"].min()
        if orh - orl <= 0:
            continue
        side, entry_i = 0, None
        for i in range(n_or, len(day) - 1):
            c = day.loc[i, "close"]
            if c > orh:
                side, entry_i = 1, i + 1
                break
            if c < orl:
                side, entry_i = -1, i + 1
                break
        if side == 0:
            continue
        entry = day.loc[entry_i, "open"] + side * SLIP
        stop = orl if side == 1 else orh
        risk_ps = abs(entry - stop)
        if risk_ps <= 0:
            continue
        target = entry + side * target_r * risk_ps
        shares = int(min(equity * RISK_PCT / risk_ps, equity / entry))
        if shares < 1:
            continue
        exit_px, reason = None, None
        for j in range(entry_i, len(day)):
            hm, hi, lo = day.loc[j, "hm"], day.loc[j, "high"], day.loc[j, "low"]
            if hm >= EXIT_TIME:
                exit_px, reason = day.loc[j, "open"], "time"
                break
            hit_stop = lo <= stop if side == 1 else hi >= stop
            hit_tgt = hi >= target if side == 1 else lo <= target
            if hit_stop:
                exit_px, reason = stop, "stop"
                break
            if hit_tgt:
                exit_px, reason = target, "target"
                break
        if exit_px is None:
            exit_px, reason = day.loc[len(day) - 1, "close"], "close"
        exit_px -= side * SLIP
        pnl = side * (exit_px - entry) * shares
        equity += pnl
        trades.append(dict(date=date, side=side, shares=shares, entry=entry, exit=exit_px,
                           reason=reason, r=pnl / (risk_ps * shares), pnl=pnl, equity=equity))
    return pd.DataFrame(trades), df


def report(sym, tr, df):
    if tr.empty:
        print(f"{sym}: nenhuma operação")
        return
    eq = pd.concat([pd.Series([START_EQUITY]), tr["equity"]]).reset_index(drop=True)
    dd = (eq / eq.cummax() - 1).min()
    wins, losses = tr[tr.pnl > 0], tr[tr.pnl <= 0]
    loss_sum = abs(losses.pnl.sum())
    pf = wins.pnl.sum() / loss_sum if loss_sum > 0 else float("inf")
    daily = tr.set_index("date")["pnl"] / START_EQUITY
    sharpe = daily.mean() / daily.std() * np.sqrt(252) if daily.std() > 0 else 0.0
    first, last = df.iloc[0], df.iloc[-1]
    bh = (last.close / first.close - 1) * 100
    days = df["date"].nunique()
    print(f"\n=== {sym}  ORB {OR_MIN}min  alvo {TARGET_R}R  risco {RISK_PCT*100:.1f}%/trade ===")
    print(f"período        : {first.timestamp:%Y-%m-%d} a {last.timestamp:%Y-%m-%d}  ({days} pregões)")
    print(f"operações      : {len(tr)}  (long {int((tr.side==1).sum())}, short {int((tr.side==-1).sum())})")
    print(f"taxa de acerto : {len(wins)/len(tr)*100:.1f}%")
    print(f"R médio        : {tr.r.mean():+.3f}   profit factor: {pf:.2f}")
    print(f"saídas         : {tr.reason.value_counts().to_dict()}")
    print(f"resultado líq. : ${tr.pnl.sum():+,.0f}  ({tr.pnl.sum()/START_EQUITY*100:+.2f}%)")
    print(f"drawdown máx.  : {dd*100:.2f}%")
    print(f"Sharpe (diário): {sharpe:.2f}")
    print(f"buy & hold     : {bh:+.2f}% no mesmo período (referência)")
    tr.to_csv(DATA_DIR / f"bt_orb_{sym}.csv", index=False)


if __name__ == "__main__":
    syms = sys.argv[1:] or SYMBOLS
    for s in syms:
        tr, df = run(s)
        report(s, tr, df)
