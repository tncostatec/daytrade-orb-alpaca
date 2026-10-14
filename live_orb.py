"""Executor PAPER do ORB na Alpaca. Um trade por dia, ordem bracket, encerra 15:55 ET.

Uso:
  python live_orb.py            # opera SPY no pregão de hoje (aguarda abertura)
  python live_orb.py QQQ        # outro símbolo
  python live_orb.py SPY --test # testa encanamento: dados de ontem + bracket de 1 ação cancelada
"""
import csv
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
from alpaca.data.enums import DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, StockLatestTradeRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderClass, OrderSide, PositionSide, QueryOrderStatus, TimeInForce
from alpaca.trading.requests import GetOrdersRequest, MarketOrderRequest, StopLossRequest, TakeProfitRequest

from backtest_orb import EXIT_TIME, OR_MIN, RISK_PCT, TARGET_R
from config import API_KEY, JOURNAL_DIR, MAX_SESSIONS, OR_ATR_MAX, PAPER, SECRET_KEY

ET = ZoneInfo("America/New_York")
SYMBOL = next((a for a in sys.argv[1:] if not a.startswith("--")), "SPY")
TEST = "--test" in sys.argv
USE_FILTER = "--no-filter" not in sys.argv
N_OR = OR_MIN // 5
JOURNAL_COLS = ["date", "symbol", "side", "qty", "entry", "stop", "target", "exit", "pnl", "reason"]

trading = TradingClient(API_KEY, SECRET_KEY, paper=PAPER)
data = StockHistoricalDataClient(API_KEY, SECRET_KEY)

today = datetime.now(ET).date()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    handlers=[logging.FileHandler(JOURNAL_DIR / f"live_{today}.log", encoding="utf-8"),
              logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger().info


def retry(fn, *a, tries=8, wait=15, **kw):
    """Repete chamadas de leitura em falha de rede (DNS, timeout). Nunca usar em submit."""
    for i in range(tries):
        try:
            return fn(*a, **kw)
        except Exception as e:
            if i == tries - 1:
                raise
            log(f"erro de rede ({e.__class__.__name__}); tentativa {i + 1}/{tries} em {wait}s")
            time.sleep(wait)


def now():
    return datetime.now(ET)


def at(day, hhmm):
    h, m = map(int, hhmm.split(":"))
    return datetime(day.year, day.month, day.day, h, m, tzinfo=ET)


def sleep_until(t):
    s = (t - now()).total_seconds()
    if s > 0:
        time.sleep(s)


def bars(day):
    """Barras de 5 min completas do dia, a partir de 09:30 ET."""
    req = StockBarsRequest(symbol_or_symbols=SYMBOL, timeframe=TimeFrame(5, TimeFrameUnit.Minute),
                           start=at(day, "09:30"), end=at(day, "16:00"), feed=DataFeed.IEX)
    df = retry(data.get_stock_bars, req).df
    if df.empty:
        return df
    df = df.xs(SYMBOL, level="symbol").reset_index()
    df["timestamp"] = df["timestamp"].dt.tz_convert(ET)
    return df[df.timestamp <= now() - timedelta(minutes=5)]


def atr14(day):
    """ATR dos 14 pregões anteriores a `day`, agregando barras 5min do horário regular
    (mesmo cálculo do backtest/filters.py)."""
    req = StockBarsRequest(symbol_or_symbols=SYMBOL, timeframe=TimeFrame(5, TimeFrameUnit.Minute),
                           start=at(day - timedelta(days=35), "09:30"), end=at(day, "09:29"), feed=DataFeed.IEX)
    df = retry(data.get_stock_bars, req).df.xs(SYMBOL, level="symbol").reset_index()
    df["timestamp"] = df["timestamp"].dt.tz_convert(ET)
    hm = df["timestamp"].dt.strftime("%H:%M")
    df = df[(hm >= "09:30") & (hm < "16:00")]
    d = df.groupby(df["timestamp"].dt.date).agg(high=("high", "max"), low=("low", "min"), close=("close", "last"))
    prev = d["close"].shift(1)
    tr = pd.concat([d.high - d.low, (d.high - prev).abs(), (d.low - prev).abs()], axis=1).max(axis=1)
    return float(tr.dropna().tail(14).mean())


def last_price():
    req = StockLatestTradeRequest(symbol_or_symbols=SYMBOL, feed=DataFeed.IEX)
    return float(retry(data.get_stock_latest_trade, req)[SYMBOL].price)


def position():
    return next((p for p in retry(trading.get_all_positions) if p.symbol == SYMBOL), None)


def equity():
    return float(retry(trading.get_account).equity)


def flatten(reason):
    # O cancelamento é assíncrono: enquanto as pernas do bracket vivem, elas seguram a
    # quantidade (held_for_orders) e o fechamento a mercado é recusado com
    # "insufficient qty available". Esperar a corretora liberar antes de zerar.
    trading.cancel_orders()
    req = GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=[SYMBOL])
    for _ in range(15):
        if not retry(trading.get_orders, req):
            break
        time.sleep(2)
    else:
        log("ordens abertas ainda não liberadas após 30s; tentando zerar mesmo assim")
    if position() is None:
        return
    trading.close_position(SYMBOL)
    # O fechamento também é assíncrono: só declarar encerrado quando a posição sumir.
    # E NUNCA chamar cancel_orders() depois daqui: em 22/09/2026 a chamada que vinha logo
    # após este flatten cancelou a própria ordem de fechamento 135 ms depois de roteada,
    # e o short atravessou o fechamento sem stop nem alvo.
    for _ in range(30):
        time.sleep(2)
        if position() is None:
            log(f"posição encerrada a mercado ({reason})")
            return
    log(f"POSIÇÃO AINDA ABERTA 60s após o fechamento a mercado ({reason}) — conferir na Alpaca.")


def avisar_tela(texto, segundos):
    """Janela do `msg.exe` (a mesma do check_dia.py), que some sozinha depois de `segundos`.
    Nunca derruba o executor: se o aviso falhar, só fica no log."""
    try:
        subprocess.run(["msg.exe", os.environ.get("USERNAME", "*"), f"/TIME:{max(int(segundos), 60)}",
                        f"[day trade {SYMBOL}] {texto}"], check=False, timeout=15)
    except Exception as e:
        log(f"aviso na tela falhou: {e}")


def sizing(side, px, orh, orl, equity):
    stop = orl if side == 1 else orh
    risk_ps = abs(px - stop)
    if risk_ps <= 0:
        return 0, stop, px
    shares = int(min(equity * RISK_PCT / risk_ps, equity / px))
    target = round(px + side * TARGET_R * risk_ps, 2)
    return shares, round(stop, 2), target


def bracket(side, qty, stop, target):
    req = MarketOrderRequest(
        symbol=SYMBOL, qty=qty,
        side=OrderSide.BUY if side == 1 else OrderSide.SELL,
        time_in_force=TimeInForce.DAY, order_class=OrderClass.BRACKET,
        take_profit=TakeProfitRequest(limit_price=target),
        stop_loss=StopLossRequest(stop_price=stop),
    )
    return trading.submit_order(req)


def journal(**row):
    path = JOURNAL_DIR / "trades.csv"
    new = not path.exists()
    full = {c: "" for c in JOURNAL_COLS}
    full.update(date=today, symbol=SYMBOL, **row)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=JOURNAL_COLS)
        if new:
            w.writeheader()
        w.writerow(full)


def sessions():
    """Pregões já registrados para o símbolo e se hoje já foi registrado."""
    path = JOURNAL_DIR / "trades.csv"
    if not path.exists():
        return 0, False
    with open(path, encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r["symbol"] == SYMBOL]
    return len(rows), any(r["date"] == str(today) for r in rows)


def exit_fill(entry_id):
    """Preço médio da ordem que encerrou a posição hoje (perna do bracket ou fechamento a mercado)."""
    req = GetOrdersRequest(status=QueryOrderStatus.CLOSED, symbols=[SYMBOL], after=at(today, "09:30"), limit=50)
    orders = list(retry(trading.get_orders, req))
    flat = orders + [leg for o in orders if o.legs for leg in o.legs]
    fills = [o for o in flat if o.filled_avg_price and str(o.id) != str(entry_id)]
    fills.sort(key=lambda o: o.filled_at)
    return float(fills[-1].filled_avg_price) if fills else ""


def decidir_entrada(post, orh, orl):
    """Decide a entrada olhando o PRIMEIRO rompimento do dia, não o preço de agora.

    Devolve ('aguardar'|'entrar'|'perdido', side, barra). 'perdido' é o caso de o
    executor ter caído e voltado depois do rompimento: entrar agora seria uma operação
    diferente da que o backtest mediu, então o dia não é operado nem registrado.
    Uma barra de tolerância cobre atraso na publicação dos dados pela corretora.
    """
    p = post.reset_index(drop=True)
    fora = p[(p.close > orh) | (p.close < orl)]
    if fora.empty:
        return "aguardar", 0, None
    i = int(fora.index[0])
    barra = p.iloc[i]
    if len(p) - 1 - i > 1:
        return "perdido", 0, barra
    return "entrar", (1 if barra.close > orh else -1), barra


def monitorar_saida(exit_t):
    """Segura a posição até stop/alvo ou até o horário de saída, e zera o que sobrar."""
    try:
        while now() < exit_t:
            time.sleep(30)
            if position() is None:
                log("posição fechada por stop ou alvo")
                return "stop_or_target"
        flatten("horário de saída")
        return "time"
    except Exception as e:
        log(f"erro no monitoramento: {e}; zerando por segurança")
        try:
            flatten("erro")
            return "error"
        except Exception as e2:
            # Nunca deixar a exceção matar o processo aqui: sem isto o journal do dia
            # não é escrito e a posição fica aberta sem ninguém saber (04/09/2026).
            log(f"FALHA AO ZERAR: {e2}. POSIÇÃO PODE ESTAR ABERTA E SEM PROTEÇÃO — conferir na Alpaca.")
            return "error_open"


def retomar(pos):
    """Assume uma posição que já existia quando o executor subiu — queda e reinício no
    meio do pregão. NUNCA abre posição nova: só protege e encerra a que está lá."""
    side = 1 if pos.side == PositionSide.LONG else -1
    qty = abs(int(float(pos.qty)))
    entry = float(pos.avg_entry_price)
    pl_antes = float(pos.unrealized_pl)
    equity_ini = equity()
    stop = target = ""
    for o in retry(trading.get_orders, GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=[SYMBOL])):
        if o.stop_price:
            stop = float(o.stop_price)
        if o.limit_price:
            target = float(o.limit_price)
    exit_t = at(today, EXIT_TIME)
    log(f"RETOMADA: já havia posição de {qty} {SYMBOL} ({'COMPRA' if side == 1 else 'VENDA'}) "
        f"a {entry:.2f}, stop {stop} alvo {target}, resultado aberto ${pl_antes:+,.2f}. "
        f"Não abro posição nova; levo esta até {exit_t:%H:%M} ET.")
    reason = monitorar_saida(exit_t)
    time.sleep(10)
    # equity já embute o resultado não realizado, então a variação desde a retomada
    # somada ao que a posição acumulou antes dela dá o resultado do dia inteiro.
    pnl = (equity() - equity_ini) + pl_antes
    log(f"resultado do dia (retomada): ${pnl:+,.2f}")
    journal(side=side, qty=qty, entry=entry, stop=stop, target=target,
            exit=exit_fill(None), pnl=round(pnl, 2), reason=f"retomada_{reason}")


def test_mode():
    day = today - timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    b = bars(day)
    log(f"[teste] {SYMBOL} barras de {day}: {len(b)}")
    orb = b.head(N_OR)
    orh, orl = orb.high.max(), orb.low.min()
    log(f"[teste] range {OR_MIN}min: {orl:.2f} – {orh:.2f}")
    atr = atr14(day)
    log(f"[teste] ATR14 {atr:.2f}  OR/ATR {(orh - orl) / atr:.3f}  limite {OR_ATR_MAX[SYMBOL]}")
    post = b.iloc[N_OR:]
    brk = post[(post.close > orh) | (post.close < orl)]
    log(f"[teste] primeiro rompimento: {brk.iloc[0].timestamp:%H:%M} close={brk.iloc[0].close:.2f}" if not brk.empty else "[teste] sem rompimento")
    px = last_price()
    log(f"[teste] último preço {px:.2f}  equity {equity():,.0f}")
    qty, stop, target = 1, round(px * 0.97, 2), round(px * 1.03, 2)
    o = bracket(1, qty, stop, target)
    log(f"[teste] bracket 1 ação aceita: id={o.id} status={o.status} stop={stop} alvo={target}")
    trading.cancel_order_by_id(o.id)
    time.sleep(2)
    o2 = trading.get_order_by_id(o.id)
    log(f"[teste] cancelada: status={o2.status}")
    log("[teste] encanamento OK")


def main():
    # Antes de qualquer coisa: se já existe posição, o executor caiu no meio do pregão.
    # Assumir a posição existente em vez de avaliar sinal — senão abriria uma segunda.
    aberta = position()
    if aberta is not None:
        return retomar(aberta)
    done, today_done = sessions()
    if today_done:
        log(f"{today} já registrado no journal; nada a fazer")
        return
    if done >= MAX_SESSIONS:
        log(f"prova concluída: {done} pregões registrados (limite {MAX_SESSIONS}). Aguardando revisão do Tiago.")
        return
    log(f"pregão {done + 1}/{MAX_SESSIONS} da prova de uso")
    clock = retry(trading.get_clock)
    if not clock.is_open:
        nxt = clock.next_open.astimezone(ET)
        if nxt.date() != today:
            log(f"sem pregão hoje; próxima abertura {nxt:%Y-%m-%d %H:%M} ET. saindo.")
            return
        log(f"aguardando abertura às {nxt:%H:%M} ET")
        sleep_until(nxt + timedelta(seconds=5))

    or_end = at(today, "09:30") + timedelta(minutes=OR_MIN)
    exit_t = at(today, EXIT_TIME)
    log(f"{SYMBOL}: pregão aberto. range até {or_end:%H:%M} ET, saída forçada {exit_t:%H:%M} ET")
    sleep_until(or_end + timedelta(seconds=20))

    b = bars(today)
    for _ in range(6):
        if len(b) >= N_OR:
            break
        time.sleep(20)
        b = bars(today)
    if len(b) < N_OR:
        log(f"só {len(b)} barras até {or_end:%H:%M}; abortando o dia")
        return
    orb = b.head(N_OR)
    orh, orl = float(orb.high.max()), float(orb.low.min())
    log(f"range de abertura: {orl:.2f} – {orh:.2f}  (amplitude {orh - orl:.2f})")
    if USE_FILTER:
        atr = atr14(today)
        ratio = (orh - orl) / atr
        limite = OR_ATR_MAX[SYMBOL]
        log(f"filtro OR/ATR14: {ratio:.3f} (ATR14 {atr:.2f}, limite {limite})")
        if ratio > limite:
            log("range de abertura largo demais; dia filtrado, sem operação")
            journal(side=0, qty=0, pnl=0, reason="filtered")
            return

    side, barra = 0, None
    post = b.iloc[N_OR:]
    while True:
        if not post.empty:
            status, side, barra = decidir_entrada(post, orh, orl)
            if status == "perdido":
                log(f"ROMPIMENTO PERDIDO: a barra de {barra.timestamp:%H:%M} rompeu enquanto o "
                    "executor estava fora do ar. Não entro atrasado; dia sem registro.")
                return
            if status == "entrar":
                break
        if now() >= exit_t:
            break
        nxt = now().replace(second=0, microsecond=0)
        nxt += timedelta(minutes=5 - nxt.minute % 5, seconds=12)
        sleep_until(nxt)
        post = bars(today).iloc[N_OR:]
    if side == 0:
        log("sem rompimento até a saída; sem operação hoje")
        journal(side=0, qty=0, pnl=0, reason="no_signal")
        return
    log(f"rompimento {'ALTA' if side == 1 else 'BAIXA'} na barra {barra.timestamp:%H:%M} close={barra.close:.2f}")

    equity0 = equity()
    px = last_price()
    qty, stop, target = sizing(side, px, orh, orl, equity0)
    if qty < 1:
        log("tamanho < 1 ação; sem operação")
        journal(side=side, qty=0, pnl=0, reason="too_small")
        return
    log(f"ordem: {'COMPRA' if side == 1 else 'VENDA'} {qty} {SYMBOL} ~{px:.2f}  stop {stop}  alvo {target}  "
        f"risco ~${abs(px - stop) * qty:,.0f} ({RISK_PCT * 100:.1f}% de {equity0:,.0f})")
    try:
        o = bracket(side, qty, stop, target)
    except Exception as e:
        log(f"ordem rejeitada: {e}")
        journal(side=side, qty=qty, stop=stop, target=target, pnl=0, reason="rejected")
        return
    fill = None
    for _ in range(30):
        time.sleep(2)
        o = retry(trading.get_order_by_id, o.id)
        if o.filled_avg_price:
            fill = float(o.filled_avg_price)
            break
    log(f"executada: {o.status} qty={o.filled_qty} preço médio={fill}")
    # Desligar o PC agora mata o executor antes da saída forçada, e o bracket é DAY: stop e
    # alvo expiram no fechamento e a posição dormiria sem proteção (achado em 30/09/2026 —
    # em 25 e 29/09 o PC desligou antes das 16:55 BRT; eram dias filtrados, por sorte).
    ate = (exit_t + timedelta(minutes=2)).astimezone()
    avisar_tela(f"POSICAO ABERTA de {qty} {SYMBOL}. NAO desligue o PC antes das {ate:%H:%M} - "
                f"o stop expira no fechamento. Se precisar desligar, zere a posicao na Alpaca antes.",
                (exit_t - now()).total_seconds())

    reason = monitorar_saida(exit_t)
    time.sleep(10)
    equity1 = equity()
    pnl = equity1 - equity0
    # O preço médio lido logo após a entrada pode ser de execução parcial (16/09/2026:
    # 98 de 131 ações); o journal precisa do preço médio final da ordem inteira.
    o_fim = retry(trading.get_order_by_id, o.id)
    if o_fim.filled_avg_price:
        fill = float(o_fim.filled_avg_price)
    exit_px = exit_fill(o.id)
    log(f"resultado do dia: ${pnl:+,.2f}  entrada {fill} saída {exit_px}  equity {equity0:,.0f} -> {equity1:,.0f}")
    journal(side=side, qty=qty, entry=fill, stop=stop, target=target, exit=exit_px, pnl=round(pnl, 2), reason=reason)


if __name__ == "__main__":
    if TEST:
        test_mode()
    else:
        main()
