"""Registro em sombra: qual teria sido a operação nos dias que o filtro barrou.

NÃO opera. Não manda ordem, não cria cliente de trading, não escreve em
`trades.csv`. Só lê barras já publicadas e simula o trade hipotético do dia com as
MESMAS regras de `backtest_orb.run()`. Grava em `journal/sombra.csv`.

Por que existe (decidido em 09/09/2026): o filtro OR/ATR barra ~58% dos pregões, e
sem isto a pergunta "o filtro está pagando o próprio aluguel?" só teria resposta
remoendo os mesmos dois anos de histórico — que foi como o filtro nasceu. A sombra
coleta a evidência PARA FRENTE, em dias que a regra nunca viu. Ao fim da prova dá
para comparar o R médio dos dias operados com o dos dias barrados.

Nos dias operados de verdade a sombra também é gravada: aí ela serve de conferência
do próprio simulador (deve bater lado, stop e alvo com a linha real do `trades.csv`).

Uso:
  python sombra.py                # o pregão de hoje (recusa se ainda não fechou)
  python sombra.py 2026-09-04     # um dia específico
  python sombra.py --backfill     # todo pregão do trades.csv que ainda não tem sombra
"""
import csv
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

# Sob `pythonw` (a tarefa agendada) não há console e `sys.stdout` é nulo: sem redirecionar,
# o primeiro print mataria o script em silêncio. Rodando na mão o console existe e a saída
# continua na tela — inclusive o resumo, que é o motivo de rodar na mão.
if sys.stdout is None:
    _ROOT = Path(__file__).resolve().parent
    (_ROOT / "journal").mkdir(exist_ok=True)
    sys.stdout = sys.stderr = open(_ROOT / "journal" / "sombra.log", "a", encoding="utf-8", buffering=1)

import pandas as pd  # noqa: E402
from alpaca.data.enums import DataFeed  # noqa: E402
from alpaca.data.historical import StockHistoricalDataClient  # noqa: E402
from alpaca.data.requests import StockBarsRequest  # noqa: E402
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit  # noqa: E402

from backtest_orb import EXIT_TIME, OR_MIN, RISK_PCT, SLIP, START_EQUITY, TARGET_R  # noqa: E402
from config import API_KEY, JOURNAL_DIR, OR_ATR_MAX, SECRET_KEY  # noqa: E402

ET = ZoneInfo("America/New_York")
SYMBOL = next((a for a in sys.argv[1:] if not a.startswith("--") and not a[0].isdigit()), "SPY")
N_OR = OR_MIN // 5
COLS = ["date", "symbol", "or_atr", "limite", "filtrado", "side", "qty",
        "entry", "stop", "target", "exit", "r", "pnl_ref", "reason"]

# Cliente de DADOS apenas — de propósito não existe TradingClient neste arquivo.
data = StockHistoricalDataClient(API_KEY, SECRET_KEY)


def log(msg):
    print(f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}")


def at(day, hhmm):
    h, m = map(int, hhmm.split(":"))
    return datetime(day.year, day.month, day.day, h, m, tzinfo=ET)


def bars(day, inicio="09:30", fim="16:00"):
    req = StockBarsRequest(symbol_or_symbols=SYMBOL, timeframe=TimeFrame(5, TimeFrameUnit.Minute),
                           start=at(day, inicio), end=at(day, fim), feed=DataFeed.IEX)
    df = data.get_stock_bars(req).df
    if df.empty:
        return df
    df = df.xs(SYMBOL, level="symbol").reset_index()
    df["timestamp"] = df["timestamp"].dt.tz_convert(ET)
    df["hm"] = df["timestamp"].dt.strftime("%H:%M")
    return df


def atr14(day):
    """ATR dos 14 pregões anteriores a `day` — mesmo cálculo de live_orb.atr14()."""
    req = StockBarsRequest(symbol_or_symbols=SYMBOL, timeframe=TimeFrame(5, TimeFrameUnit.Minute),
                           start=at(day - timedelta(days=35), "09:30"), end=at(day, "09:29"),
                           feed=DataFeed.IEX)
    df = data.get_stock_bars(req).df.xs(SYMBOL, level="symbol").reset_index()
    df["timestamp"] = df["timestamp"].dt.tz_convert(ET)
    hm = df["timestamp"].dt.strftime("%H:%M")
    df = df[(hm >= "09:30") & (hm < "16:00")]
    d = df.groupby(df["timestamp"].dt.date).agg(high=("high", "max"), low=("low", "min"),
                                                close=("close", "last"))
    prev = d["close"].shift(1)
    tr = pd.concat([d.high - d.low, (d.high - prev).abs(), (d.low - prev).abs()], axis=1).max(axis=1)
    return float(tr.dropna().tail(14).mean())


def simula(day_bars):
    """O trade hipotético do dia, regra por regra igual a `backtest_orb.run()`.

    Patrimônio de referência fixo (START_EQUITY) em vez do saldo real: o que interessa
    comparar entre dias é o `r` (resultado em múltiplos do risco), que não depende do
    tamanho da conta. `pnl_ref` é só a tradução em dólares desse mesmo `r`.
    """
    d = day_bars.reset_index(drop=True)
    if len(d) < N_OR + 3 or d.loc[0, "hm"] != "09:30":
        return {"reason": "dia_incompleto"}
    orh = float(d.loc[:N_OR - 1, "high"].max())
    orl = float(d.loc[:N_OR - 1, "low"].min())
    if orh - orl <= 0:
        return {"reason": "dia_incompleto"}

    side, entry_i = 0, None
    for i in range(N_OR, len(d) - 1):
        c = d.loc[i, "close"]
        if c > orh:
            side, entry_i = 1, i + 1
            break
        if c < orl:
            side, entry_i = -1, i + 1
            break
    if side == 0:
        return {"reason": "sem_rompimento"}

    entry = float(d.loc[entry_i, "open"]) + side * SLIP
    stop = orl if side == 1 else orh
    risk_ps = abs(entry - stop)
    if risk_ps <= 0:
        return {"reason": "dia_incompleto"}
    target = entry + side * TARGET_R * risk_ps
    shares = int(min(START_EQUITY * RISK_PCT / risk_ps, START_EQUITY / entry))
    if shares < 1:
        return {"reason": "muito_pequeno"}

    exit_px, reason = None, None
    for j in range(entry_i, len(d)):
        hm, hi, lo = d.loc[j, "hm"], d.loc[j, "high"], d.loc[j, "low"]
        if hm >= EXIT_TIME:
            exit_px, reason = float(d.loc[j, "open"]), "time"
            break
        # stop antes do alvo quando os dois cabem na mesma barra (conservador)
        if (lo <= stop if side == 1 else hi >= stop):
            exit_px, reason = stop, "stop"
            break
        if (hi >= target if side == 1 else lo <= target):
            exit_px, reason = target, "target"
            break
    if exit_px is None:
        exit_px, reason = float(d.loc[len(d) - 1, "close"]), "close"
    exit_px -= side * SLIP
    pnl = side * (exit_px - entry) * shares
    return {"side": side, "qty": shares, "entry": round(entry, 2), "stop": round(stop, 2),
            "target": round(target, 2), "exit": round(exit_px, 2),
            "r": round(pnl / (risk_ps * shares), 3), "pnl_ref": round(pnl, 2), "reason": reason}


def ja_registrados():
    path = JOURNAL_DIR / "sombra.csv"
    if not path.exists():
        return set()
    with open(path, encoding="utf-8") as f:
        return {r["date"] for r in csv.DictReader(f) if r["symbol"] == SYMBOL}


def grava(linha):
    path = JOURNAL_DIR / "sombra.csv"
    novo = not path.exists()
    full = {c: "" for c in COLS}
    full.update(linha)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        if novo:
            w.writeheader()
        w.writerow(full)


def registra(dia):
    """Calcula e grava a sombra de um pregão. Devolve False se o dia não deu para medir."""
    if str(dia) in ja_registrados():
        log(f"{dia}: sombra já registrada; pulando")
        return False
    b = bars(dia)
    if b.empty:
        log(f"{dia}: sem barras (feriado ou fim de semana); nada a registrar")
        return False
    # Só registra pregão encerrado: dia pela metade daria sombra errada e definitiva.
    if b["hm"].max() < EXIT_TIME:
        log(f"{dia}: pregão ainda não chegou às {EXIT_TIME} ET (última barra {b['hm'].max()}); "
            "deixando para a próxima rodada")
        return False

    orh = float(b.loc[:N_OR - 1, "high"].max())
    orl = float(b.loc[:N_OR - 1, "low"].min())
    atr = atr14(dia)
    ratio = (orh - orl) / atr
    limite = OR_ATR_MAX[SYMBOL]
    r = simula(b)
    linha = {"date": dia, "symbol": SYMBOL, "or_atr": round(ratio, 3), "limite": limite,
             "filtrado": "sim" if ratio > limite else "nao", **r}
    grava(linha)
    log(f"{dia}: OR/ATR {ratio:.3f} ({'FILTRADO' if ratio > limite else 'operável'}) -> "
        f"{linha.get('reason')} r={linha.get('r', '')}")
    return True


def resumo():
    path = JOURNAL_DIR / "sombra.csv"
    if not path.exists():
        return
    with open(path, encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r["symbol"] == SYMBOL and r["r"] != ""]
    if not rows:
        return
    print()
    log(f"--- sombra acumulada ({SYMBOL}) ---")
    for grupo, titulo in (("nao", "dias que o filtro DEIXOU passar"), ("sim", "dias que o filtro BARROU")):
        g = [float(r["r"]) for r in rows if r["filtrado"] == grupo]
        if g:
            acertos = sum(1 for x in g if x > 0)
            log(f"{titulo:34s}: n={len(g):2d}  R médio {sum(g) / len(g):+.3f}  "
                f"acerto {acertos / len(g) * 100:.0f}%  soma {sum(g):+.2f}R")
    barrados = [float(r["r"]) for r in rows if r["filtrado"] == "sim"]
    if barrados:
        log("leitura: R médio POSITIVO nos barrados = o filtro está deixando dinheiro na mesa; "
            "NEGATIVO = ele está evitando prejuízo. Amostra pequena não decide nada.")


def dias_do_journal():
    path = JOURNAL_DIR / "trades.csv"
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return [r["date"] for r in csv.DictReader(f) if r["symbol"] == SYMBOL]


def main():
    if "--backfill" in sys.argv:
        # Pega os dias já registrados no journal e os últimos 10 pregões, para não
        # depender de o executor ter fechado a linha do dia (08/09 não fechou).
        hoje = datetime.now(ET).date()
        candidatos = {date.fromisoformat(d) for d in dias_do_journal()}
        candidatos |= {hoje - timedelta(days=i) for i in range(10)}
        for dia in sorted(candidatos):
            if dia.weekday() < 5 and dia <= hoje:
                registra(dia)
    else:
        alvo = next((a for a in sys.argv[1:] if a[0].isdigit()), None)
        registra(date.fromisoformat(alvo) if alvo else datetime.now(ET).date())
    resumo()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        log("FALHA no registro em sombra:")
        traceback.print_exc(file=sys.stdout)
        raise
