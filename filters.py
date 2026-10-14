"""Filtros de regime para o ORB, avaliados ano 1 vs ano 2 (fora da amostra).

Cada filtro escolhe os dias em que se opera, usando só informação disponível
antes da entrada (dados do dia anterior ou dos primeiros minutos do dia).
"""
import numpy as np
import pandas as pd

from backtest_orb import START_EQUITY, load, run
from config import SYMBOLS

OR, TR = 15, 2.0


def daily_features(df):
    g = df.groupby("date", sort=True)
    d = pd.DataFrame({
        "open": g["open"].first(), "high": g["high"].max(),
        "low": g["low"].min(), "close": g["close"].last(),
        "v_first": g["volume"].first(),
    })
    prev_close = d["close"].shift(1)
    tr = pd.concat([d.high - d.low, (d.high - prev_close).abs(), (d.low - prev_close).abs()], axis=1).max(axis=1)
    d["atr14"] = tr.rolling(14).mean().shift(1)            # ATR dos 14 dias anteriores
    d["atr_pct"] = d["atr14"] / prev_close * 100
    d["gap_pct"] = ((d["open"] - prev_close) / prev_close * 100).abs()
    d["rvol"] = d["v_first"] / d["v_first"].rolling(14).mean().shift(1)
    orb = df[df["hm"] < f"{9 + (30 + OR) // 60:02d}:{(30 + OR) % 60:02d}"].groupby("date")
    d["or_atr"] = (orb["high"].max() - orb["low"].min()) / d["atr14"]
    d["prev_ret"] = (prev_close / d["close"].shift(2) - 1).abs() * 100
    return d


def stats(tr):
    if tr.empty or len(tr) < 10:
        return "n<10"
    eq = pd.concat([pd.Series([START_EQUITY]), tr["equity"]]).reset_index(drop=True)
    dd = (eq / eq.cummax() - 1).min() * 100
    w, l = tr[tr.pnl > 0].pnl.sum(), abs(tr[tr.pnl <= 0].pnl.sum())
    pf = w / l if l > 0 else float("inf")
    t = tr.r.mean() / tr.r.std() * np.sqrt(len(tr)) if tr.r.std() > 0 else 0.0
    return f"n={len(tr):3d} ret={tr.pnl.sum() / START_EQUITY * 100:+6.2f}% PF={pf:4.2f} R={tr.r.mean():+.3f} t={t:4.2f} DD={dd:5.2f}%"


for sym in SYMBOLS:
    df = load(sym)
    feat = daily_features(df)
    mid = df["date"].min() + pd.Timedelta(days=365)
    # limiares definidos pela mediana do ANO 1 apenas (evita olhar o ano 2)
    y1 = feat[feat.index < mid]
    filters = {
        "sem filtro": pd.Series(True, index=feat.index),
        "ATR% alto (> mediana ano1)": feat.atr_pct > y1.atr_pct.median(),
        "ATR% baixo (< mediana ano1)": feat.atr_pct < y1.atr_pct.median(),
        "gap > 0.3%": feat.gap_pct > 0.3,
        "gap > mediana ano1": feat.gap_pct > y1.gap_pct.median(),
        "rvol 1a barra > 1": feat.rvol > 1.0,
        "rvol 1a barra > 1.5": feat.rvol > 1.5,
        "OR estreito (< mediana ano1)": feat.or_atr < y1.or_atr.median(),
        "OR largo (> mediana ano1)": feat.or_atr > y1.or_atr.median(),
        "dia anterior forte (>1%)": feat.prev_ret > 1.0,
    }
    print(f"\n=== {sym}  ORB {OR}min alvo {TR}R — filtros, ano 1 (dentro) vs ano 2 (fora) ===")
    for name, mask in filters.items():
        allowed = set(mask[mask.fillna(False)].index)
        sub = df[df["date"].isin(allowed)]
        s1 = stats(run(sym, OR, TR, sub[sub["date"] < mid])[0])
        s2 = stats(run(sym, OR, TR, sub[sub["date"] >= mid])[0])
        print(f"{name:32s} ano1: {s1}\n{'':32s} ano2: {s2}")
