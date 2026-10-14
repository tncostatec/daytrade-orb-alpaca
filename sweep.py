"""Robustez do ORB: varredura de parâmetros + divisão dentro/fora da amostra + t-stat."""
import numpy as np
import pandas as pd

from backtest_orb import START_EQUITY, load, run
from config import SYMBOLS

OR_MINS = [5, 10, 15, 30]
TARGETS = [1.0, 1.5, 2.0, 3.0]


def stats(tr):
    if tr.empty:
        return dict(n=0, ret=0.0, pf=0.0, r=0.0, t=0.0, dd=0.0)
    eq = pd.concat([pd.Series([START_EQUITY]), tr["equity"]]).reset_index(drop=True)
    dd = (eq / eq.cummax() - 1).min() * 100
    w, l = tr[tr.pnl > 0].pnl.sum(), abs(tr[tr.pnl <= 0].pnl.sum())
    pf = w / l if l > 0 else float("inf")
    t = tr.r.mean() / tr.r.std() * np.sqrt(len(tr)) if tr.r.std() > 0 else 0.0
    return dict(n=len(tr), ret=tr.pnl.sum() / START_EQUITY * 100, pf=pf, r=tr.r.mean(), t=t, dd=dd)


for sym in SYMBOLS:
    df = load(sym)
    print(f"\n=== {sym}: varredura (retorno % em 2 anos / profit factor / t-stat do R médio) ===")
    print("OR\\alvo " + "".join(f"{t:>16}R" for t in TARGETS))
    for om in OR_MINS:
        row = f"{om:>3}min  "
        for tg in TARGETS:
            s = stats(run(sym, om, tg, df)[0])
            row += f"  {s['ret']:+6.1f}% {s['pf']:4.2f} t={s['t']:4.1f}"
        print(row)

    print(f"\n--- {sym}: dentro (ano 1) vs fora da amostra (ano 2), ORB 15min alvo 2R ---")
    mid = df["date"].min() + pd.Timedelta(days=365)
    for label, part in (("ano 1", df[df["date"] < mid]), ("ano 2", df[df["date"] >= mid])):
        s = stats(run(sym, 15, 2.0, part)[0])
        print(f"{label}: trades={s['n']}  retorno={s['ret']:+.2f}%  PF={s['pf']:.2f}  "
              f"R médio={s['r']:+.3f}  t={s['t']:.2f}  DD={s['dd']:.2f}%")
